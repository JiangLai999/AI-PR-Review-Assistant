"""审查任务管理：异步执行 + 真实逐文件进度 + 服务端取消。

背景：原先 `/api/review` 是同步 POST，导致两个问题 ——
界面只能盲等（进度回调根本没接到前端），而且"取消"只是断开 HTTP 连接，
服务端仍在继续调用模型、继续计费。

这里把审查变成任务：

    POST /api/review          -> 立即返回 job_id，后台线程执行
    GET  /api/review/<id>/events -> SSE 推进度事件
    POST /api/review/<id>/cancel -> 真正请求停止（在文件之间生效）

取消的语义要说清楚：**无法中断已经在飞的那一次模型调用**，
所以停止发生在文件边界 —— 不再开始新文件，已完成的文件结果保留。
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ai_pr_review.config import AppConfig
from ai_pr_review.services.review_orchestrator import (
    ReviewArtifacts,
    ReviewCancelled,
    ReviewOrchestrator,
)


@dataclass(slots=True)
class ReviewJob:
    """一次审查任务的运行时状态。"""

    job_id: str
    pr_url: str
    created_at: float = field(default_factory=time.time)
    status: str = "queued"  # queued | running | done | failed | cancelled
    total_files: int = 0
    completed_files: int = 0
    current_file: str = ""
    artifacts: ReviewArtifacts | None = None
    error: str = ""
    cancel_requested: bool = False

    @property
    def progress(self) -> float:
        if self.total_files <= 0:
            return 0.0
        return min(1.0, self.completed_files / self.total_files)

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "pr_url": self.pr_url,
            "status": self.status,
            "total_files": self.total_files,
            "completed_files": self.completed_files,
            "current_file": self.current_file,
            "progress": round(self.progress, 4),
            "error": self.error,
            "elapsed_seconds": round(time.time() - self.created_at, 2),
            "run_id": self.artifacts.run_id if self.artifacts else None,
        }


class ReviewJobManager:
    """内存中的任务表 + SSE 事件队列。

    单机本地工具，任务不跨进程持久化：进程重启后任务消失，
    但已完成的结果已经写进 SQLite，可以用 run_id 从历史里找回。
    """

    MAX_JOBS = 50

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._jobs: dict[str, ReviewJob] = {}
        self._subscribers: dict[str, list[queue.Queue[str]]] = {}
        self._lock = threading.Lock()

    # ---- 查询 -----------------------------------------------------

    def get(self, job_id: str) -> ReviewJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return [job.snapshot() for job in jobs[:limit]]

    # ---- 事件流 ---------------------------------------------------

    def subscribe(self, job_id: str) -> queue.Queue[str]:
        channel: queue.Queue[str] = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(channel)
        return channel

    def unsubscribe(self, job_id: str, channel: queue.Queue[str]) -> None:
        with self._lock:
            channels = self._subscribers.get(job_id)
            if not channels:
                return
            if channel in channels:
                channels.remove(channel)
            if not channels:
                self._subscribers.pop(job_id, None)

    def _emit(self, job: ReviewJob, event: str, **extra: Any) -> None:
        payload = {"event": event, **job.snapshot(), **extra}
        line = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            channels = list(self._subscribers.get(job.job_id, []))
        for channel in channels:
            channel.put(line)

    # ---- 取消 -----------------------------------------------------

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.status in {"done", "failed", "cancelled"}:
            return False
        job.cancel_requested = True
        job.status = "cancelling"
        self._emit(job, "cancelling")
        return True

    def _check_cancelled(self, job: ReviewJob) -> None:
        if job.cancel_requested:
            raise ReviewCancelled()

    # ---- 启动 -----------------------------------------------------

    def start(self, pr_url: str) -> ReviewJob:
        job = ReviewJob(job_id=uuid.uuid4().hex[:12], pr_url=pr_url)
        with self._lock:
            self._jobs[job.job_id] = job
            if len(self._jobs) > self.MAX_JOBS:
                # 按创建时间淘汰最旧的已结束任务
                finished = [
                    j for j in self._jobs.values() if j.status in {"done", "failed", "cancelled"}
                ]
                for stale in sorted(finished, key=lambda j: j.created_at)[
                    : len(self._jobs) - self.MAX_JOBS
                ]:
                    self._jobs.pop(stale.job_id, None)
                    self._subscribers.pop(stale.job_id, None)

        thread = threading.Thread(
            target=self._run, args=(job,), name=f"review-{job.job_id}", daemon=True
        )
        thread.start()
        return job

    def _run(self, job: ReviewJob) -> None:
        """后台线程入口：把编排过程中的异常翻译成任务状态。"""
        try:
            job.status = "running"
            self._emit(job, "started")
            asyncio.run(self._execute(job))
        except ReviewCancelled:
            job.status = "cancelled"
            self._emit(job, "cancelled", message="已按请求停止，已完成的文件结果已保留。")
        except Exception as exc:  # noqa: BLE001 - 任何失败都要反馈到界面
            job.status = "failed"
            job.error = str(exc)
            self._emit(job, "failed", message=str(exc))
        else:
            job.status = "done"
            self._emit(job, "done")

    async def _execute(self, job: ReviewJob) -> None:
        """执行审查，把编排器的进度回调翻译成 SSE 事件并检查取消。"""
        config = self._config

        def on_file_start(filename: str, _model: str) -> None:
            self._check_cancelled(job)
            job.current_file = filename
            self._emit(job, "file_started", filename=filename)

        def on_file_done(filename: str) -> None:
            job.completed_files += 1
            job.current_file = ""
            self._emit(job, "file_done", filename=filename)

        def on_stage(stage: str, detail: str = "") -> None:
            self._check_cancelled(job)
            self._emit(job, "stage", stage=stage, message=detail)

        orchestrator = ReviewOrchestrator(config)
        artifacts = await orchestrator.review(
            job.pr_url,
            progress_callback=on_file_start,
            file_done_callback=on_file_done,
            stage_callback=on_stage,
            cancel_check=lambda: job.cancel_requested,
        )
        job.artifacts = artifacts
        job.total_files = artifacts.filter_result.included_count


__all__ = ["ReviewCancelled", "ReviewJob", "ReviewJobManager"]
