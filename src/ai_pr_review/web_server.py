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
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.services.review_orchestrator import ReviewOrchestrator
from ai_pr_review.web_config import apply_config_update, build_config_view
from ai_pr_review.web_jobs import ReviewJobManager

MAX_BODY_BYTES = 64 * 1024

# 前端构建产物目录（随包安装）
WEB_STATIC_DIR = Path(__file__).resolve().parent / "web_static"

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("font/woff2", ".woff2")


def count_deterministic_rules() -> int:
    """统计确定性规则的**去重**条数，避免界面里写死的数字随代码漂移。

    - `python_ast_analyzer` 用关键字参数 `rule="..."`；
      `static_analyzer` 用位置参数（`..., 0.98, "dynamic_execution",`）。
    - 少数规则在两个分析器里各有实现（例如 `tls_verification_disabled`
      在逐行与 AST 两侧都会命中），这里按规则名去重，因此结果小于实现数。
    """
    import re

    from ai_pr_review.services.analyzers import python_ast_analyzer, static_analyzer

    names: set[str] = set()
    for module in (static_analyzer, python_ast_analyzer):
        source = Path(module.__file__).read_text(encoding="utf-8")
        names.update(re.findall(r'rule="([a-z][a-z0-9_]+)"', source))
        names.update(re.findall(r'0\.\d+,\s*\n\s*"([a-z][a-z0-9_]+)",', source))
    return len(names)


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

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if self._declared_body_too_large():
            # 依据 Content-Length 提前拒绝，不尝试读取请求体：客户端可能并未
            # 真的发送这么多字节，阻塞读取会把连接挂住。
            self._send_json(400, {"error": "request body is too large"}, close=True)
            return
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
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
        self._send_json(
            200,
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

    def _declared_body_too_large(self) -> bool:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return True
        return length > MAX_BODY_BYTES

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
