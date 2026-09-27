"""Small local web adapter for the modular monolith.

The server intentionally uses the standard library so the CLI remains installable
without a second runtime stack. It is bound to localhost by default.

前端是一个 React + Vite 应用，构建产物位于包内 `web_static/`，随包分发。
因此 `pip install` 之后无需 Node 即可直接提供完整界面。
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ai_pr_review.config import AppConfig
from ai_pr_review.credentials import collect_status
from ai_pr_review.demo_runner import demo_cases_payload, run_demo_case
from ai_pr_review.services.exceptions import InvalidPRURLError
from ai_pr_review.services.publish_service import (
    PublishError,
    PublishService,
    stored_run_pr_data,
)
from ai_pr_review.services.report_renderer import ReportRenderer
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.services.review_orchestrator import ReviewOrchestrator
from ai_pr_review.utils.github_url_parser import parse_pr_url
from ai_pr_review.web_config import apply_config_update, build_config_view
from ai_pr_review.web_jobs import ReviewJobManager

MAX_BODY_BYTES = 64 * 1024

# 写端点只接受"同源浏览器"或"本地无 Origin 客户端"（curl / CLI）。
# 威胁模型：工作台监听回环且无鉴权，任何网页都能对 127.0.0.1:8787 发简单请求
# （`Content-Type: text/plain` 不触发预检），而 /api/publish 会真的往 GitHub 写东西。
_LOCAL_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}
_PUBLISH_STATUS_CODES = {
    "invalid_request": 400,
    "not_found": 404,
    "not_publishable": 409,
    "missing_credentials": 503,
    "publish_failed": 502,
}

# `/api/chat` 的失败码 → HTTP（与 publish 同风格：服务层只给 code + message）。
_CHAT_STATUS_CODES = {
    "invalid_request": 400,
    "not_found": 404,
    "missing_api_key": 503,
    "chat_failed": 502,
}


def _origin_is_local(origin: str) -> bool:
    """`http://127.0.0.1:8787` / `http://localhost:5173` 这类本机来源放行。"""
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return (parsed.hostname or "").lower() in _LOCAL_ORIGIN_HOSTS


def _published_ledger_path(config: AppConfig) -> Path:
    """发布账本放在结果库同目录：`<db 目录>/published-comments.json`。

    TUI 的账本只活在会话内存里（关掉就忘）；Web 是无状态的，必须落盘才能回答
    "这条 run 是不是已经发过评论了"。
    """
    return Path(str(config.result_store.db_path)).parent / "published-comments.json"


def _load_published_ids(config: AppConfig) -> set[str]:
    try:
        payload = json.loads(_published_ledger_path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(payload, list):
        return set()
    return {str(item) for item in payload if isinstance(item, str) and item.strip()}


def _remember_published(config: AppConfig, run_id: str) -> None:
    """记下已发布的 run（尽力而为：账本写失败不能把已成功的发布报成失败）。"""
    ids = _load_published_ids(config)
    ids.add(run_id)
    path = _published_ledger_path(config)
    temporary = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(sorted(ids), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(path)
    except OSError:
        pass


def _publish_response(payload: dict[str, Any]) -> dict[str, Any]:
    """把 `PublishService` 的载荷规整成 Web 契约（status 三态 + 回链 + 人话提示）。"""
    response = dict(payload)
    if response.get("status") == "published" and response.get("already_published"):
        response["status"] = "already_published"
    response.setdefault("requires_confirmation", response.get("status") == "preview")
    response.setdefault("comment_url", "")
    response.setdefault("comment_id", "")
    response.setdefault("already_published", False)
    response["message"] = str(response.get("text") or response.get("message") or "")
    return response

# 前端构建产物目录（随包安装）
WEB_STATIC_DIR = Path(__file__).resolve().parent / "web_static"

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("font/woff2", ".woff2")


def count_deterministic_rules() -> int:
    """统计确定性规则的**去重**条数，避免界面里写死的数字随代码漂移。

    P6 之后规则文案与身份统一收敛在 `analyzers.rule_catalog`，所以这里直接读目录，
    不再扫描分析器源码里的调用形态（那种正则会在重构后静默失准）。少数规则在两个
    分析器里各有实现（例如 `tls_verification_disabled` 在逐行与 AST 两侧都会命中），
    目录按 rule_id 去重，因此结果小于目录键数。
    """
    from ai_pr_review.services.analyzers.rule_catalog import all_rule_ids

    return len(all_rule_ids())


def tree_sitter_available() -> bool:
    """tree-sitter 语法包是否可用（决定上下文走语法树还是正则）。"""
    from ai_pr_review.services.context_builder import _load_tree_sitter_language

    return all(
        _load_tree_sitter_language(language) is not None
        for language in ("python", "javascript", "typescript")
    )


class ReviewWebHandler(BaseHTTPRequestHandler):
    """HTTP handler exposing plan, review, history, report and feedback endpoints."""

    config: AppConfig
    jobs: ReviewJobManager
    # 配置落盘路径。测试通过覆盖这个类属性来隔离，避免写到真实用户配置。
    config_path: Path | None = None

    @property
    def job_manager(self) -> ReviewJobManager:
        """惰性获取任务管理器：服务启动时挂一份，测试里没挂就按需创建。"""
        manager = type(self).__dict__.get("jobs")
        if manager is None:
            manager = ReviewJobManager(self.config)
            type(self).jobs = manager
        return manager

    # ---- GET ------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/demo/cases":
            self._send_json(200, {"cases": demo_cases_payload()})
            return
        if path == "/api/demo/run":
            key = (
                parse_qs(parsed.query).get("case", ["sql-injection"])[0] or "sql-injection"
            ).strip()
            try:
                self._send_json(200, run_demo_case(key))
            except ValueError as exc:
                self._send_json(404, {"error": str(exc)})
            except Exception as exc:
                # Keep browser clients on a JSON error path instead of closing
                # the socket and surfacing a misleading "Failed to fetch".
                self._send_json(500, {"error": f"Demo execution failed: {exc}"})
            return
        if path == "/api/health":
            self._send_json(200, {"ok": True, "service": "ai-pr-review"})
            return
        if path == "/api/history":
            self._handle_history(parse_qs(parsed.query))
            return
        if path == "/api/report":
            self._handle_report(parse_qs(parsed.query))
            return
        if path == "/api/report/export":
            self._handle_report_export(parse_qs(parsed.query))
            return
        if path == "/api/benchmark":
            self._handle_benchmark(parse_qs(parsed.query))
            return
        if path == "/api/meta":
            self._handle_meta()
            return
        if path == "/api/credentials":
            self._handle_credentials(parse_qs(parsed.query))
            return
        if path == "/api/config":
            self._send_json(
                200, build_config_view(self.config, config_path=self.config_path).to_dict()
            )
            return
        if path == "/api/jobs":
            self._send_json(200, {"jobs": self.job_manager.list_recent(10)})
            return
        if path.startswith("/api/jobs/"):
            self._handle_job_get(path, parse_qs(parsed.query))
            return
        if path.startswith("/api/"):
            self._send_json(404, {"error": "Not found"})
            return

        self._serve_frontend(path)

    # ---- POST -----------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        """不实现 CORS 预检：回 405，且**不**发任何 `Access-Control-*` 头。

        只要浏览器无法完成预检，跨站脚本就拿不到响应；配合写端点的
        Content-Type / Origin 校验，构成完整的第一层跨站防线。
        """
        self._send_json(405, {"error": "OPTIONS not supported"}, close=True)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if self._declared_body_too_large():
            # 依据 Content-Length 提前拒绝，不尝试读取请求体：客户端可能并未
            # 真的发送这么多字节，阻塞读取会把连接挂住。
            self._send_json(400, {"error": "request body is too large"}, close=True)
            return
        if self._reject_cross_site():
            return
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        if path == "/api/publish":
            self._handle_publish(payload)
            return
        if path == "/api/chat":
            self._handle_chat(payload)
            return

        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = path[len("/api/jobs/") : -len("/cancel")].strip("/")
            if self.job_manager.cancel(job_id):
                self._send_json(200, {"ok": True, "job_id": job_id, "message": "已请求停止。"})
            else:
                self._send_json(404, {"error": f"任务不存在或已结束：{job_id}"})
            return

        if path not in {"/api/plan", "/api/review", "/api/feedback", "/api/config"}:
            self._send_json(404, {"error": "Not found"})
            return

        if path == "/api/feedback":
            self._handle_feedback(payload)
            return
        if path == "/api/config":
            self._handle_config_save(payload)
            return

        try:
            pr_url = str(payload.get("pr_url", "")).strip()
            if not pr_url:
                raise ValueError("pr_url is required")
            orchestrator = ReviewOrchestrator(self.config)
            if path == "/api/plan":
                artifacts = asyncio.run(orchestrator.plan_only(pr_url))
            elif payload.get("async_job"):
                # 任务化：立即返回 job_id，进度走 SSE，可用 /cancel 真正停止
                job = self.job_manager.start(pr_url)
                self._send_json(202, job.snapshot())
                return
            else:
                artifacts = asyncio.run(orchestrator.review(pr_url))
            result: dict[str, Any] = {
                "pr": _pr_payload(artifacts.pr_data),
                "filter": artifacts.filter_result.to_dict(),
                "plan": (
                    artifacts.review_plan.model_dump(mode="json")
                    if artifacts.review_plan is not None
                    else None
                ),
                "validation": artifacts.validation_summary,
                "cross_file_impacts": [
                    impact.model_dump(mode="json") for impact in artifacts.cross_file_impacts
                ],
                "interface_impacts": [impact.to_dict() for impact in artifacts.interface_impacts],
                "run": {
                    "id": artifacts.run_id,
                    "duration_seconds": artifacts.duration_seconds,
                    "total_cost": artifacts.total_cost,
                },
            }
            if artifacts.review_result is not None:
                result["review"] = artifacts.review_result.model_dump(mode="json")
            self._send_json(200, result)
        except Exception as exc:  # pragma: no cover - exercised through the live server
            self._send_json(400, {"error": str(exc)})

    # ---- 前端静态资源 ---------------------------------------------

    def _serve_frontend(self, path: str) -> None:
        """提供 SPA 构建产物。

        约定：
        - `/` 与 `/index.html` 返回 SPA 入口；
        - `/static/<file>` 映射到 web_static 根目录下的文件；
        - 其余路径回退到入口，交给前端 hash 路由处理。
        """
        index_path = WEB_STATIC_DIR / "index.html"
        if not index_path.exists():
            self._send_json(
                503,
                {
                    "error": "Web UI assets are missing from the installed package.",
                    "expected_at": str(WEB_STATIC_DIR),
                    "hint": "Rebuild with: cd web && npm install && npm run build",
                },
            )
            return

        if path in {"", "/", "/index.html"}:
            self._send_file(index_path)
            return

        relative = path[len("/static/") :] if path.startswith("/static/") else path.lstrip("/")
        candidate = (WEB_STATIC_DIR / relative).resolve()
        try:
            candidate.relative_to(WEB_STATIC_DIR.resolve())
        except ValueError:
            self._send_json(404, {"error": "Not found"})
            return

        if candidate.is_file():
            self._send_file(candidate)
            return

        # SPA 回退
        self._send_file(index_path)

    def _send_file(self, file_path: Path) -> None:
        try:
            body = file_path.read_bytes()
        except OSError:
            self._send_json(404, {"error": "Not found"})
            return
        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
            "image/svg+xml",
        }:
            content_type = f"{content_type}; charset=utf-8"
        # 哈希文件名的资源可长期缓存，入口 HTML 不缓存。
        cache = (
            "public, max-age=31536000, immutable" if file_path.name != "index.html" else "no-store"
        )
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    # ---- 业务处理器 -----------------------------------------------

    def _handle_credentials(self, query: dict[str, list[str]]) -> None:
        """报告 GitHub 与模型凭证是否真的可用。

        `?probe=0` 时只做本地检查（是否填写），不发网络请求 —— 用于首屏快速渲染。
        """
        probe = (query.get("probe", ["1"])[0] or "1") not in {"0", "false", "no"}
        try:
            report = collect_status(self.config, probe=probe)
            self._send_json(200, report.to_dict())
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    def _handle_config_save(self, payload: dict[str, Any]) -> None:
        """保存设置页提交的配置；可选先做凭证校验。"""
        if payload.get("validate"):
            report = collect_status(self.config, probe=True)
            if not report.ok:
                self._send_json(
                    400,
                    {
                        "error": "凭证校验未通过，未保存。",
                        "credentials": report.to_dict(),
                    },
                )
                return
        try:
            result = apply_config_update(self.config, payload, config_path=self.config_path)
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})
            return
        # `ok=False` = 提交里有不支持的键/非法值：**必须**回 400，否则设置页会把
        # "什么都没保存"当成成功（2026-09-27 opencode 实测复现的静默失败）。
        # 载荷形状保持不变，前端仍可读 changed/message 做局部提示。
        status = 200 if result.ok else 400
        self._send_json(
            status,
            {
                "ok": result.ok,
                "changed": result.changed,
                "message": result.message,
                "save_key_used": result.save_key_used,
                "config": build_config_view(self.config, config_path=self.config_path).to_dict(),
            },
        )

    def _handle_job_get(self, path: str, query: dict[str, list[str]]) -> None:
        """`/api/jobs/<id>` 取快照，`/api/jobs/<id>/events` 走 SSE 推进度。"""
        rest = path[len("/api/jobs/") :].strip("/")
        job_id, _, action = rest.partition("/")
        job = self.job_manager.get(job_id)
        if job is None:
            self._send_json(404, {"error": f"Unknown job: {job_id}"})
            return

        if action == "events":
            self._stream_job_events(job_id)
            return
        if action == "":
            artifacts = job.artifacts
            payload = job.snapshot()
            if artifacts is not None:
                payload["result"] = {
                    "pr": _pr_payload(artifacts.pr_data),
                    "filter": artifacts.filter_result.to_dict(),
                    "plan": (
                        artifacts.review_plan.model_dump(mode="json")
                        if artifacts.review_plan is not None
                        else None
                    ),
                    "validation": artifacts.validation_summary,
                    "cross_file_impacts": [
                        impact.model_dump(mode="json") for impact in artifacts.cross_file_impacts
                    ],
                    "interface_impacts": [
                        impact.to_dict() for impact in artifacts.interface_impacts
                    ],
                    "run": {
                        "id": artifacts.run_id,
                        "duration_seconds": artifacts.duration_seconds,
                        "total_cost": artifacts.total_cost,
                    },
                    "review": (
                        artifacts.review_result.model_dump(mode="json")
                        if artifacts.review_result is not None
                        else None
                    ),
                }
            self._send_json(200, payload)
            return
        self._send_json(404, {"error": "Not found"})

    def _stream_job_events(self, job_id: str) -> None:
        """SSE：把任务事件实时推给浏览器，直到任务结束。"""
        channel = self.job_manager.subscribe(job_id)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            # 先补一条当前快照，避免订阅前的事件丢失
            job = self.job_manager.get(job_id)
            if job is not None:
                self._write_sse(json.dumps(job.snapshot(), ensure_ascii=False))
            while True:
                try:
                    line = channel.get(timeout=15)
                except Exception:
                    # 心跳：保持连接存活，也让服务端能感知客户端断开
                    self.wfile.write(b": keep-alive\r\n\r\n")
                    self.wfile.flush()
                    current = self.job_manager.get(job_id)
                    if current is None or current.status in {"done", "failed", "cancelled"}:
                        break
                    continue
                self._write_sse(line)
                try:
                    parsed = json.loads(line)
                except Exception:
                    continue
                if parsed.get("event") in {"done", "failed", "cancelled"}:
                    break
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            self.job_manager.unsubscribe(job_id, channel)

    def _write_sse(self, data: str) -> None:
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _handle_history(self, query: dict[str, list[str]]) -> None:
        try:
            limit = int(query.get("limit", ["20"])[0])
        except ValueError:
            self._send_json(400, {"error": "limit must be an integer"})
            return
        limit = max(1, min(limit, 200))
        try:
            store = ResultStore(config=self.config.result_store)
            self._send_json(
                200,
                {
                    "runs": store.list_runs(limit=limit),
                    "statistics": store.get_statistics(),
                },
            )
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    def _handle_report(self, query: dict[str, list[str]]) -> None:
        run_id = (query.get("run_id", [""])[0] or "").strip()
        if not run_id:
            self._send_json(400, {"error": "run_id is required"})
            return
        try:
            store = ResultStore(config=self.config.result_store)
            result = store.get_result(run_id)
            if result is None:
                self._send_json(404, {"error": f"Unknown run_id: {run_id}"})
                return
            metadata = store.get_run_metadata(run_id)
            runs = store.list_runs(limit=200)
            record = next((run for run in runs if run.get("id") == run_id), {})
            self._send_json(
                200,
                {
                    "run_id": run_id,
                    "run": record,
                    "review": result.model_dump(mode="json"),
                    "plan": metadata.get("review_plan"),
                    "validation": metadata.get("validation_summary", {}),
                    "cross_file_impacts": metadata.get("cross_file_impacts", []),
                    "interface_impacts": metadata.get("interface_impacts", []),
                    "feedback": store.list_feedback(run_id),
                },
            )
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    def _handle_report_export(self, query: dict[str, list[str]]) -> None:
        """`GET /api/report/export?run_id=&format=markdown|json`。

        真相源是 `ReportRenderer.render_markdown`（与 CLI `export-run` 同一套渲染），
        不是前端自己拼的 Markdown——否则 CLI 导出与 Web 导出会各自漂移。
        """
        run_id = (query.get("run_id", [""])[0] or "").strip()
        output_format = (query.get("format", ["markdown"])[0] or "markdown").strip().lower()
        if not run_id:
            self._send_json(400, {"error": "run_id is required"})
            return
        if output_format not in {"markdown", "json"}:
            self._send_json(400, {"error": "format must be markdown or json"})
            return
        try:
            store = ResultStore(config=self.config.result_store)
            result = store.get_result(run_id)
            summary = store.get_run_summary(run_id)
            if result is None or summary is None:
                self._send_json(404, {"error": f"Unknown run_id: {run_id}"})
                return
            metadata = store.get_run_metadata(run_id)
            if output_format == "json":
                self._send_json(
                    200,
                    {
                        "run_id": run_id,
                        "run": summary,
                        "review": result.model_dump(mode="json"),
                        "plan": metadata.get("review_plan"),
                        "validation": metadata.get("validation_summary", {}),
                        "cross_file_impacts": metadata.get("cross_file_impacts", []),
                        "interface_impacts": metadata.get("interface_impacts", []),
                        "feedback": store.list_feedback(run_id),
                    },
                )
                return
            pr_url = str(summary.get("pr_url") or "").strip()
            parsed = parse_pr_url(pr_url)
            pr_data = stored_run_pr_data(summary, metadata, parsed, pr_url)
            files_changed = int(summary.get("total_files") or 0)
            markdown = ReportRenderer(self.config.report_renderer).render_markdown(
                result,
                pr_data,
                files_changed=files_changed or None,
            )
            filename = f"pr{parsed.pr_number}-{run_id[:8]}.md"
            self._send_download(
                markdown.encode("utf-8"),
                "text/markdown; charset=utf-8",
                filename,
            )
        except InvalidPRURLError as exc:
            self._send_json(
                409,
                {"error": f"该 Run 的 PR 链接不是 GitHub PR URL，无法导出报告：{exc}"},
            )
        except Exception as exc:  # pragma: no cover - exercised through the live server
            self._send_json(400, {"error": str(exc)})

    def _handle_benchmark(self, query: dict[str, list[str]]) -> None:
        """返回基准测试报告，供工作台展示策略准确率。"""
        strategy = (query.get("strategy", ["combined"])[0] or "combined").strip()
        try:
            from ai_pr_review.benchmark import STRATEGIES, run_all_strategies, run_benchmark

            if strategy == "all":
                self._send_json(
                    200,
                    {name: report.to_dict() for name, report in run_all_strategies().items()},
                )
                return
            if strategy not in STRATEGIES:
                self._send_json(
                    400,
                    {
                        "error": f"Unknown strategy: {strategy}",
                        "available": sorted(STRATEGIES),
                    },
                )
                return
            self._send_json(200, run_benchmark(strategy).to_dict())
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    def _handle_meta(self) -> None:
        """返回运行时的真实元信息，供界面显示而不是硬编码数字。"""
        try:
            from ai_pr_review.config import MODEL_PROVIDER_PRESETS

            self._send_json(
                200,
                {
                    "rule_count": count_deterministic_rules(),
                    "provider_count": len(MODEL_PROVIDER_PRESETS),
                    "tree_sitter_available": tree_sitter_available(),
                    "cross_file_review_enabled": bool(
                        self.config.ai_client.enable_cross_file_review
                    ),
                    "static_analysis_enabled": bool(self.config.ai_client.enable_static_analysis),
                    "model": self.config.ai_client.model,
                    "default_branch": True,
                },
            )
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    def _handle_feedback(self, payload: dict[str, Any]) -> None:
        run_id = str(payload.get("run_id", "")).strip()
        finding_id = str(payload.get("finding_id", "")).strip()
        status = str(payload.get("status", "")).strip()
        note = str(payload.get("note", ""))
        if not run_id or not finding_id:
            self._send_json(400, {"error": "run_id and finding_id are required"})
            return
        try:
            store = ResultStore(config=self.config.result_store)
            if store.get_result(run_id) is None:
                self._send_json(404, {"error": f"Unknown run_id: {run_id}"})
                return
            store.save_feedback(run_id, finding_id, status, note)
            self._send_json(
                200,
                {"ok": True, "run_id": run_id, "finding_id": finding_id, "status": status},
            )
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover
            self._send_json(400, {"error": str(exc)})

    # ---- plumbing -------------------------------------------------

    def _handle_publish(self, payload: dict[str, Any]) -> None:
        """`POST /api/publish {run_id, confirm}`。

        `confirm=false`（默认）**只预览**，绝不碰 GitHub；`confirm=true` 才真发，
        发完把 run 记进落盘账本（`_published_ledger_path`）。第二次发布同一 run 时
        载荷里 `status=already_published` 且带警告文案——按契约"照发 + 警告"，
        不静默跳过（用户明确二次确认过）。
        """
        run_id = str(payload.get("run_id", "") or "").strip()
        if not run_id:
            self._send_json(400, {"error": "run_id is required", "code": "invalid_request"})
            return
        published_ids = _load_published_ids(self.config)
        confirm = payload.get("confirm") is True
        try:
            service = PublishService(self.config)
            if confirm:
                outcome = service.publish(run_id=run_id, published_run_ids=published_ids)
                _remember_published(self.config, run_id)
            else:
                outcome = service.preview(run_id=run_id, published_run_ids=published_ids)
            self._send_json(200, _publish_response(outcome))
        except PublishError as exc:
            self._send_json(
                _PUBLISH_STATUS_CODES.get(exc.code, 400),
                {"error": exc.message, "code": exc.code},
            )
        except Exception as exc:  # pragma: no cover - exercised through the live server
            self._send_json(500, {"error": str(exc)})

    def _handle_chat(self, payload: dict[str, Any]) -> None:
        """`POST /api/chat {run_id?, text}` —— 对某次审查追问（无状态，服务层在 `web_chat`）。

        这里只做协议 ↔ 服务的翻译：服务层抛 `ChatError(code, message)`，本层按 code
        映射 HTTP（400/404/502/503）；`/api/chat` 同样走 `do_POST` 顶部的跨站守卫。
        """
        text = str(payload.get("text", "") or "").strip()
        run_id = str(payload.get("run_id", "") or "").strip()
        # 延迟导入：`web_chat` 是后加模块，导入失败不应让整个服务起不来。
        from ai_pr_review.web_chat import ChatError, answer_with_context

        try:
            outcome = asyncio.run(answer_with_context(self.config, run_id=run_id, text=text))
            self._send_json(200, outcome)
        except ChatError as exc:
            self._send_json(
                _CHAT_STATUS_CODES.get(exc.code, 400),
                {"error": exc.message, "code": exc.code},
            )
        except Exception as exc:  # pragma: no cover - exercised through the live server
            self._send_json(500, {"error": str(exc)})

    def _declared_body_too_large(self) -> bool:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return True
        return length > MAX_BODY_BYTES

    def _reject_cross_site(self) -> bool:
        """跨站守卫：被拒时已经回过响应，返回 True 表示调用方应直接 return。

        三层（任意一层不合规即 415）：
        1. `Content-Type: application/json`——浏览器把跨站 `text/plain` POST 当"简单请求"，
           不做预检；强制 JSON 让这类请求先撞墙。
        2. `Sec-Fetch-Site` 非 `same-origin`/`none` 一律拒绝（现代浏览器一定带）。
        3. `Origin` 存在时其 host 必须是本机（`127.0.0.1`/`localhost`/`::1`）；
           CLI/curl 不带 Origin，直接放行。
        """
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self._send_json(
                415,
                {"error": "Content-Type must be application/json"},
                close=True,
            )
            return True
        fetch_site = (self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if fetch_site and fetch_site not in {"same-origin", "none"}:
            self._send_json(415, {"error": "cross-site request rejected"}, close=True)
            return True
        origin = (self.headers.get("Origin") or "").strip()
        if origin and not _origin_is_local(origin):
            self._send_json(415, {"error": "cross-site request rejected"}, close=True)
            return True
        return False

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _send_json(self, status: int, payload: dict[str, Any], *, close: bool = False) -> None:
        self._send(
            status,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json; charset=utf-8",
            close=close,
        )

    def _send_download(self, body: bytes, content_type: str, filename: str) -> None:
        """带 `Content-Disposition` 的下载响应（导出报告用）。"""
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send(self, status: int, body: bytes, content_type: str, *, close: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def _pr_payload(pr_data: Any) -> dict[str, Any]:
    """序列化 PR 数据并补充前端指标条需要的 files_changed。

    PRData.changed_files_count 是 property，model_dump 不会带出它；
    前端 `pr.files_changed` 依赖这个字段（缺失时会显示 "—"）。
    """
    payload = pr_data.model_dump(mode="json")
    payload["files_changed"] = pr_data.changed_files_count
    return payload


def _is_temp_dir_path(path: Path) -> bool:
    """判断路径是否位于系统临时目录之下（pytest 夹具、沙箱常把库写到那里）。"""
    try:
        resolved = path.resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        return temp_root == resolved or temp_root in resolved.parents
    except OSError:  # pragma: no cover
        return False


def serve(
    config: AppConfig,
    host: str = "127.0.0.1",
    port: int = 8787,
    config_path: Path | None = None,
) -> None:
    """Run the local web workbench."""
    handler = type(
        "ConfiguredReviewWebHandler",
        (ReviewWebHandler,),
        {
            "config": config,
            "jobs": ReviewJobManager(config),
            # 否则 `pr-review --config X serve` 的配置页会读写默认用户配置。
            "config_path": config_path,
        },
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"PR智审 Web 工作台已启动：http://{host}:{port}")

    if not (WEB_STATIC_DIR / "index.html").exists():
        print(f"警告：前端构建产物缺失（{WEB_STATIC_DIR}），请先执行 cd web && npm run build")

    # 数据库若因权限问题改道，必须显式告知：否则客户端口会"看起来像丢了历史"。
    try:
        store = ResultStore(config=config.result_store)
        if store.using_fallback_path:
            print(
                "警告：配置的数据库路径不可写，已改道到备用位置。\n"
                f"  配置声明：{Path(config.result_store.db_path).expanduser()}\n"
                f"  实际使用：{store.db_path}\n"
                "  历史记录会写入实际使用的位置。"
            )
        elif _is_temp_dir_path(store.db_path):
            print(
                "警告：结果库位于系统临时目录，随时可能被清理，历史记录不可靠。\n"
                f"  当前路径：{store.db_path}\n"
                "  请检查配置 result_store.db_path（通常应为 ~/.ai_pr_review/results.db）。"
            )
        else:
            print(f"结果库：{store.db_path}")
    except Exception as exc:  # pragma: no cover
        print(f"警告：无法初始化结果库：{exc}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\\nWeb 工作台已停止。")
    finally:
        server.server_close()
