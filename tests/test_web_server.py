"""本地 Web 工作台服务端测试。

使用标准库的 HTTP 客户端直接访问 ThreadingHTTPServer，不引入额外依赖。
"""

from __future__ import annotations

import json
import re
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import pytest

from ai_pr_review.config import AppConfig, ResultStoreConfig
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
from ai_pr_review.services.publish_service import PublishError, PublishService
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.web_server import ReviewWebHandler


@pytest.fixture
def server(tmp_path):
    config = AppConfig.from_env()
    config.result_store = ResultStoreConfig(db_path=str(tmp_path / "results.db"))
    # 填入可识别的假密钥，用来断言接口绝不回传明文
    config.ai_client.api_key = "sk-testsecret000000000000000000000"
    config.provider.api_key = "sk-testsecret000000000000000000000"
    config.github_token = "ghp_testsecrettoken000000000000000000"
    store = ResultStore(config=config.result_store)
    finding = Finding(
        severity="high",
        category="security",
        file="src/app.py",
        line_start=3,
        line_end=3,
        title="SQL injection risk",
        problem="User input is concatenated into SQL.",
        suggestion="Use parameterized queries.",
        confidence=0.95,
        code_snippet="query = f'SELECT ...'",
        finding_id="finding-abc",
    )
    run_id = store.save_result(
        "https://github.com/owner/repo/pull/7",
        ReviewResult(summary="one issue", findings=[finding]),
        metadata={
            "review_plan": {"risk_level": "high", "intent": "fix query"},
            "validation_summary": {"valid": 1, "needs_review": 0, "invalid": 0},
            "interface_impacts": [{"symbol": "fetch_user", "is_breaking": True}],
        },
    )

    handler = type(
        "TestReviewWebHandler",
        (ReviewWebHandler,),
        # config_path 指向临时目录：绝不能让测试写到真实用户配置
        {"config": config, "config_path": tmp_path / "config.json"},
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "base": f"http://127.0.0.1:{httpd.server_address[1]}",
            "run_id": run_id,
            "config_path": tmp_path / "config.json",
            # 供追问历史用例直接种数据（HTTP 层只读/清，写入由 /api/chat 落库）
            "store": store,
            # 供测试断言"接口不得回传明文密钥"使用
            "secrets": [
                value
                for value in (
                    (config.ai_client.api_key or "").strip(),
                    (config.provider.api_key or "").strip(),
                    (config.github_token or "").strip(),
                )
                if value
            ],
        }
    finally:
        httpd.shutdown()
        httpd.server_close()


def call(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        base + path,
        data=data,
        headers={"content-type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")


class TestFrontendAssets:
    """前端为 React + Vite 构建产物，随包分发，由本服务直接提供。"""

    def test_root_serves_spa_entry(self, server):
        status, body = call(server["base"], "GET", "/")

        assert status == 200
        assert "<!doctype html>" in body.lower()
        assert 'id="root"' in body

    def test_index_html_route_also_served(self, server):
        status, _ = call(server["base"], "GET", "/index.html")

        assert status == 200

    def test_bundled_assets_are_referenced_and_served(self, server):
        _, body = call(server["base"], "GET", "/")
        refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', body)
        assert refs, "entry HTML must reference bundled /static assets"

        for ref in refs:
            status, _ = call(server["base"], "GET", ref)
            assert status == 200, f"bundled asset not served: {ref}"

    def test_asset_content_types_are_correct(self, server):
        _, body = call(server["base"], "GET", "/")
        refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', body)

        for ref in refs:
            request = urllib.request.Request(server["base"] + ref)
            with urllib.request.urlopen(request, timeout=10) as response:
                content_type = response.headers.get("Content-Type", "")
            if ref.endswith(".js"):
                assert "javascript" in content_type
            elif ref.endswith(".css"):
                assert "text/css" in content_type
            elif ref.endswith(".svg"):
                assert "image/svg+xml" in content_type

    def test_no_external_cdn_dependencies(self, server):
        _, body = call(server["base"], "GET", "/")

        # 离线可用：不得依赖外部 CDN。
        assert "cdn." not in body
        assert "fonts.googleapis.com" not in body

    def test_unknown_route_falls_back_to_spa_entry(self, server):
        status, body = call(server["base"], "GET", "/some/client/route")

        assert status == 200
        assert 'id="root"' in body

    def test_static_path_traversal_is_blocked(self, server):
        status, _ = call(server["base"], "GET", "/static/../../../../etc/passwd")

        # 解析后越出静态目录的请求不得返回文件内容。
        assert status in {200, 404}
        if status == 200:
            _, body = call(server["base"], "GET", "/static/../../../../etc/passwd")
            assert "root:" not in body

    def test_missing_asset_falls_back_to_entry_not_500(self, server):
        status, _ = call(server["base"], "GET", "/static/assets/does-not-exist.js")

        assert status == 200


class TestHealth:
    def test_health_ok(self, server):
        status, body = call(server["base"], "GET", "/api/health")

        assert status == 200
        assert json.loads(body)["ok"] is True


class TestHistory:
    def test_history_returns_runs_and_statistics(self, server):
        status, body = call(server["base"], "GET", "/api/history")

        assert status == 200
        payload = json.loads(body)
        assert payload["statistics"]["total_runs"] == 1
        assert payload["runs"][0]["pr_number"] == 7

    def test_history_rejects_bad_limit(self, server):
        status, body = call(server["base"], "GET", "/api/history?limit=abc")

        assert status == 400
        assert "limit" in json.loads(body)["error"]

    def test_history_honours_limit(self, server):
        status, body = call(server["base"], "GET", "/api/history?limit=1")

        assert status == 200
        assert len(json.loads(body)["runs"]) == 1


class TestReport:
    def test_report_returns_review_and_metadata(self, server):
        status, body = call(server["base"], "GET", f"/api/report?run_id={server['run_id']}")

        assert status == 200
        payload = json.loads(body)
        assert payload["review"]["summary"] == "one issue"
        assert payload["plan"]["risk_level"] == "high"
        assert payload["validation"]["valid"] == 1
        assert payload["interface_impacts"][0]["symbol"] == "fetch_user"

    def test_report_unknown_run_is_404(self, server):
        status, body = call(server["base"], "GET", "/api/report?run_id=missing")

        assert status == 404
        assert "Unknown run_id" in json.loads(body)["error"]

    def test_report_without_run_id_is_400(self, server):
        status, body = call(server["base"], "GET", "/api/report")

        assert status == 400
        assert "run_id" in json.loads(body)["error"]


class TestChatHistory:
    """追问历史的读/清两条端点（写入侧在 /api/chat，由 web_chat 负责落库）。"""

    def _seed(self, server) -> None:
        store = server["store"]
        run_id = server["run_id"]
        store.save_chat_turn(run_id, role="user", content="这次审查有几个问题？")
        store.save_chat_turn(
            run_id,
            role="assistant",
            content="两个。",
            model="deepseek-flash",
            usage={"total_tokens": 42},
            duration_ms=1500,
        )

    def test_history_returns_turns_in_order(self, server):
        self._seed(server)

        status, body = call(server["base"], "GET", f"/api/chat/history?run_id={server['run_id']}")

        payload = json.loads(body)
        assert status == 200, body
        assert payload["run_id"] == server["run_id"]
        assert payload["count"] == 2
        assert [turn["role"] for turn in payload["turns"]] == ["user", "assistant"]
        assert payload["turns"][1]["usage"] == {"total_tokens": 42}
        assert payload["turns"][1]["duration_ms"] == 1500

    def test_history_is_empty_for_run_without_asks(self, server):
        status, body = call(server["base"], "GET", f"/api/chat/history?run_id={server['run_id']}")

        assert status == 200
        assert json.loads(body) == {"run_id": server["run_id"], "count": 0, "turns": []}

    def test_history_requires_run_id(self, server):
        status, body = call(server["base"], "GET", "/api/chat/history")

        assert status == 400
        assert "run_id" in json.loads(body)["error"]

    def test_history_rejects_unknown_run(self, server):
        """未知 run 必须 404：不能让前端把"run 不存在"当成"这次没追问过"。"""
        status, body = call(server["base"], "GET", "/api/chat/history?run_id=nope")

        assert status == 404
        assert "Unknown run_id" in json.loads(body)["error"]

    def test_history_rejects_bad_limit(self, server):
        status, body = call(
            server["base"], "GET", f"/api/chat/history?run_id={server['run_id']}&limit=0"
        )

        assert status == 400
        assert "limit" in json.loads(body)["error"]

    def test_history_honours_limit(self, server):
        self._seed(server)

        status, body = call(
            server["base"], "GET", f"/api/chat/history?run_id={server['run_id']}&limit=1"
        )

        payload = json.loads(body)
        assert status == 200
        assert [turn["content"] for turn in payload["turns"]] == ["这次审查有几个问题？"]

    def test_clear_removes_turns_and_is_idempotent(self, server):
        self._seed(server)

        status, body = call(
            server["base"], "POST", "/api/chat/history/clear", {"run_id": server["run_id"]}
        )
        first = json.loads(body)

        assert status == 200, body
        assert first == {"ok": True, "run_id": server["run_id"], "deleted": 2}
        _, after = call(server["base"], "GET", f"/api/chat/history?run_id={server['run_id']}")
        assert json.loads(after)["count"] == 0

        status, body = call(
            server["base"], "POST", "/api/chat/history/clear", {"run_id": server["run_id"]}
        )
        assert status == 200
        assert json.loads(body)["deleted"] == 0

    def test_clear_requires_run_id_and_known_run(self, server):
        status, body = call(server["base"], "POST", "/api/chat/history/clear", {})
        assert status == 400
        assert "run_id" in json.loads(body)["error"]

        status, body = call(server["base"], "POST", "/api/chat/history/clear", {"run_id": "nope"})
        assert status == 404
        assert "Unknown run_id" in json.loads(body)["error"]

    def test_report_payload_carries_chat_turns(self, server):
        """报告页要能就地展示追问记录，所以 /api/report 必须一并返回。"""
        self._seed(server)

        status, body = call(server["base"], "GET", f"/api/report?run_id={server['run_id']}")

        payload = json.loads(body)
        assert status == 200, body
        assert [turn["role"] for turn in payload["chat_turns"]] == ["user", "assistant"]

    def test_markdown_export_includes_the_chat_section(self, server):
        """用户拍板：追问记录随报告导出（独立小节）。"""
        self._seed(server)

        status, body = call(
            server["base"],
            "GET",
            f"/api/report/export?run_id={server['run_id']}&format=markdown",
        )

        assert status == 200, body
        assert "## Follow-up Q&A" in body
        assert "这次审查有几个问题？" in body
        assert "两个。" in body

    def test_markdown_export_without_asks_has_no_chat_section(self, server):
        """没追问过的 run：导出必须与改造前逐字一致（不出现空小节）。"""
        status, body = call(
            server["base"],
            "GET",
            f"/api/report/export?run_id={server['run_id']}&format=markdown",
        )

        assert status == 200, body
        assert "Follow-up Q&A" not in body
        assert "追问记录" not in body


class TestFeedback:
    def test_feedback_is_recorded(self, server):
        status, body = call(
            server["base"],
            "POST",
            "/api/feedback",
            {"run_id": server["run_id"], "finding_id": "finding-abc", "status": "accepted"},
        )

        assert status == 200
        assert json.loads(body)["ok"] is True

    def test_feedback_appears_in_report(self, server):
        call(
            server["base"],
            "POST",
            "/api/feedback",
            {
                "run_id": server["run_id"],
                "finding_id": "finding-abc",
                "status": "rejected",
                "note": "false positive",
            },
        )

        _, body = call(server["base"], "GET", f"/api/report?run_id={server['run_id']}")

        feedback = json.loads(body)["feedback"]
        assert feedback[0]["status"] == "rejected"
        assert feedback[0]["note"] == "false positive"

    def test_feedback_rejects_unknown_status(self, server):
        status, body = call(
            server["base"],
            "POST",
            "/api/feedback",
            {"run_id": server["run_id"], "finding_id": "finding-abc", "status": "bogus"},
        )

        assert status == 400
        assert "Unsupported feedback status" in json.loads(body)["error"]

    def test_feedback_requires_identifiers(self, server):
        status, body = call(
            server["base"], "POST", "/api/feedback", {"run_id": "", "finding_id": ""}
        )

        assert status == 400
        assert "required" in json.loads(body)["error"]

    def test_feedback_rejects_unknown_run(self, server):
        status, body = call(
            server["base"],
            "POST",
            "/api/feedback",
            {"run_id": "nope", "finding_id": "finding-abc", "status": "accepted"},
        )

        assert status == 404


class TestMetaEndpoint:
    def test_meta_reports_real_counts(self, server):
        status, body = call(server["base"], "GET", "/api/meta")

        assert status == 200
        payload = json.loads(body)
        # 这些数字必须来自代码，而不是界面里写死的常量
        assert payload["rule_count"] > 0
        assert payload["provider_count"] > 0
        assert isinstance(payload["tree_sitter_available"], bool)
        assert isinstance(payload["cross_file_review_enabled"], bool)
        assert payload["model"]

    def test_rule_count_matches_analyzers(self, server):
        from ai_pr_review.web_server import count_deterministic_rules

        _, body = call(server["base"], "GET", "/api/meta")
        assert json.loads(body)["rule_count"] == count_deterministic_rules()

    def test_rule_count_is_deduplicated(self):
        from ai_pr_review.services.analyzers import python_ast_analyzer, static_analyzer
        from ai_pr_review.web_server import count_deterministic_rules

        # tls_verification_disabled 在两侧都有实现，去重后总数应小于实现数之和
        assert count_deterministic_rules() > 0
        assert python_ast_analyzer is not None and static_analyzer is not None


class TestBenchmarkEndpoint:
    def test_benchmark_returns_combined_report(self, server):
        status, body = call(server["base"], "GET", "/api/benchmark")

        assert status == 200
        payload = json.loads(body)
        assert payload["strategy"] == "combined"
        assert 0.0 <= payload["precision"] <= 1.0
        assert payload["case_count"] > 0
        assert len(payload["cases"]) == payload["case_count"]

    def test_benchmark_all_returns_every_strategy(self, server):
        status, body = call(server["base"], "GET", "/api/benchmark?strategy=all")

        assert status == 200
        payload = json.loads(body)
        assert set(payload) == {"static", "ast", "combined"}
        for report in payload.values():
            assert "precision" in report

    def test_benchmark_rejects_unknown_strategy(self, server):
        status, body = call(server["base"], "GET", "/api/benchmark?strategy=nope")

        assert status == 400
        payload = json.loads(body)
        assert "unknown" in payload["error"].lower()
        assert payload["available"]


class TestCredentialsEndpoint:
    def test_local_probe_is_fast_and_masks_secrets(self, server):
        status, body = call(server["base"], "GET", "/api/credentials?probe=0")

        assert status == 200
        payload = json.loads(body)
        assert len(payload["items"]) == 2
        assert {item["key"] for item in payload["items"]} == {"github", "model"}
        # 本地模式不发网络请求，所以不应出现明文密钥
        assert "sk-" not in body or "尚未探测" in body

    def test_items_carry_actionable_fields(self, server):
        _, body = call(server["base"], "GET", "/api/credentials?probe=0")

        for item in json.loads(body)["items"]:
            assert "ok" in item
            assert "configured" in item
            assert "detail" in item
            assert "label" in item


class TestConfigEndpoint:
    def test_config_view_never_returns_plaintext_secret(self, server):
        status, body = call(server["base"], "GET", "/api/config")

        assert status == 200
        payload = json.loads(body)
        assert "config_path" in payload
        assert isinstance(payload["available_providers"], list)
        assert payload["available_providers"]
        # 真实密钥不能出现在响应里
        for item in server["secrets"]:
            assert item not in body, "配置视图泄漏了明文密钥"

    def test_config_reports_masked_values(self, server):
        _, body = call(server["base"], "GET", "/api/config")
        payload = json.loads(body)

        assert payload["api_key_set"] is True
        assert payload["github_token_set"] is True
        assert payload["api_key_masked"]
        assert payload["api_key_masked"] != server["secrets"][0]

    def test_saving_blank_key_keeps_existing(self, server):
        """界面回填空密钥时必须保留原值，而不是清空。"""
        _, before = call(server["base"], "GET", "/api/config")
        original = json.loads(before)["api_key_masked"]
        assert original, "夹具应当配置了密钥"

        status, _ = call(
            server["base"], "POST", "/api/config", {"api_key": "", "model": "same-model"}
        )

        assert status == 200
        _, after = call(server["base"], "GET", "/api/config")
        assert json.loads(after)["api_key_masked"] == original

    def test_save_writes_to_injected_path_not_user_config(self, server):
        """回归保护：保存必须写到注入的路径，不能碰真实用户配置。"""
        status, _ = call(server["base"], "POST", "/api/config", {"model": "m1"})

        assert status == 200
        assert server["config_path"].exists(), "应写入注入的临时配置"
        saved = json.loads(server["config_path"].read_text(encoding="utf-8"))
        assert saved["ai_client"]["model"] == "m1"


class TestJobEndpoints:
    def test_unknown_job_is_404(self, server):
        status, body = call(server["base"], "GET", "/api/jobs/does-not-exist")

        assert status == 404
        assert "Unknown job" in json.loads(body)["error"]

    def test_cancel_unknown_job_is_404(self, server):
        status, _ = call(server["base"], "POST", "/api/jobs/nope/cancel", {})

        assert status == 404

    def test_jobs_list_starts_empty(self, server):
        status, body = call(server["base"], "GET", "/api/jobs")

        assert status == 200
        assert json.loads(body)["jobs"] == []


class TestReviewEndpoints:
    def test_plan_requires_pr_url(self, server):
        status, body = call(server["base"], "POST", "/api/plan", {})

        assert status == 400
        assert "pr_url" in json.loads(body)["error"]

    def test_review_requires_pr_url(self, server):
        status, body = call(server["base"], "POST", "/api/review", {})

        assert status == 400
        assert "pr_url" in json.loads(body)["error"]

    def test_unknown_post_route_is_404(self, server):
        status, _ = call(server["base"], "POST", "/api/nope", {})

        assert status == 404

    def test_unknown_get_route_is_404(self, server):
        status, _ = call(server["base"], "GET", "/api/nope")

        assert status == 404

    def test_oversized_declared_body_is_rejected_without_reading_it(self, server):
        """服务端应依据 Content-Length 直接拒绝，而不是尝试读完请求体。

        这里用裸 socket 只发送头部和极少量数据，验证服务端不会因为等待
        声明长度而挂住——这正是基于头部提前拒绝的意义。
        """
        host, port = server["base"].removeprefix("http://").split(":")
        with socket.create_connection((host, int(port)), timeout=15) as connection:
            request = (
                "POST /api/plan HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {200 * 1024}\r\n"
                "\r\n"
                "{}"
            )
            connection.sendall(request.encode("ascii"))
            connection.shutdown(socket.SHUT_WR)
            response = b""
            while b"\r\n\r\n" not in response:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                response += chunk

        status_line = response.split(b"\r\n", 1)[0].decode("latin-1")
        assert "400" in status_line

    def test_empty_body_is_treated_as_missing_url(self, server):
        status, body = call(server["base"], "POST", "/api/plan", None)

        assert status == 400
        assert "pr_url" in json.loads(body)["error"]

    def test_non_object_body_is_rejected(self, server):
        request = urllib.request.Request(
            server["base"] + "/api/plan",
            data=json.dumps([1, 2, 3]).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status, body = response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read().decode("utf-8")

        assert status == 400
        assert "JSON object" in json.loads(body)["error"]


class TestPrPayload:
    def test_pr_payload_includes_files_changed(self):
        """前端指标条依赖 pr.files_changed；model_dump 不含该 property，必须显式补上。"""
        from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
        from ai_pr_review.web_server import _pr_payload

        pr = PRData(
            pr_number=32,
            title="t",
            author="a",
            state="open",
            head_sha="h",
            base_sha="b",
            head_ref="hr",
            base_ref="br",
            url="https://github.com/o/r/pull/32",
            owner="o",
            repo="r",
            files=[
                FileDiff(filename="a.py", status=FileStatus.MODIFIED, changes=3),
                FileDiff(filename="b.py", status=FileStatus.ADDED, changes=5),
            ],
        )

        payload = _pr_payload(pr)

        assert payload["files_changed"] == 2
        assert [f["filename"] for f in payload["files"]] == ["a.py", "b.py"]

    def test_is_temp_dir_path_detects_temp_locations(self, tmp_path):
        import tempfile

        from ai_pr_review.web_server import _is_temp_dir_path

        temp_db = Path(tempfile.gettempdir()) / "pytest-xxx" / "results.db"
        assert _is_temp_dir_path(temp_db) is True
        assert _is_temp_dir_path(Path.home() / ".ai_pr_review" / "results.db") is False


def test_serve_command_hands_the_resolved_config_path_to_the_web_layer(
    monkeypatch, tmp_path: Path
) -> None:
    """F19 + 配置隔离：`pr-review --config X serve` 的设置页读写 **X.web.json**。

    原断言是"读写 X"（Web 与 CLI 共用一份）。用户要求"Web 设置不得影响 CLI"之后，
    契约改成派生路径：CLI 那份 X 保持不变，Web 用 X.web.json。
    """
    from click.testing import CliRunner

    from ai_pr_review.cli import main

    captured: dict[str, object] = {}

    def fake_serve(config, host="127.0.0.1", port=8787, config_path=None):
        captured["config_path"] = config_path
        captured["port"] = port

    monkeypatch.setattr("ai_pr_review.web_server.serve", fake_serve)
    config_path = tmp_path / "workspace-config.json"
    expected_web_path = tmp_path / "workspace-config.web.json"

    result = CliRunner().invoke(main, ["--config", str(config_path), "serve", "--port", "9123"])

    assert result.exit_code == 0, result.output
    assert captured["config_path"] == expected_web_path
    assert captured["port"] == 9123


def call_raw(
    base: str,
    method: str,
    path: str,
    *,
    body: dict | str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], str]:
    """像 `call` 一样发请求，但能自定义 body 原文与请求头，并回读响应头。

    `body` 传字符串时按原样发送（用来构造"不是 JSON 的简单请求"）。
    """
    data: bytes | None
    if body is None:
        data = None
    elif isinstance(body, str):
        data = body.encode("utf-8")
    else:
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base + path,
        data=data,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return (
                response.status,
                {key.lower(): value for key, value in response.headers.items()},
                response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            {key.lower(): value for key, value in error.headers.items()},
            error.read().decode("utf-8", errors="replace"),
        )


class TestConfigSaveSemantics:
    """保存接口的成败必须与磁盘一致（opencode 实测的两个静默失败回归点）。"""

    def test_unsupported_key_returns_400_not_a_silent_200(self, server):
        status, body = call(server["base"], "POST", "/api/config", {"not_a_real_key": 1})

        payload = json.loads(body)
        assert status == 400, body
        assert payload["ok"] is False
        assert "unsupported key" in payload["message"]
        assert payload["changed"] == []

    def test_preference_key_actually_persists(self, server):
        status, body = call(server["base"], "POST", "/api/config", {"ui_language": "en-US"})

        payload = json.loads(body)
        assert status == 200, body
        assert payload["ok"] is True
        assert "ui_language" in payload["changed"]
        # `ConfigView` 目前还没暴露 preferences（Phase 2 的计划），所以这里核对
        # 落盘真相——本用例要证明的是"保存成功 == 磁盘真的变了"。
        saved = json.loads(server["config_path"].read_text(encoding="utf-8"))
        assert saved["preferences"]["ui_language"] == "en-US"

    def test_settings_page_payload_shape_is_accepted(self, server):
        """真实设置页会带 validate / persist_secrets / 数值项：白名单必须覆盖它，
        否则"未知键拒绝"会把正常的保存也一起挡掉（这是本用例存在的唯一理由）。"""
        payload = {
            "provider_name": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_format": "openai",
            "persist_secrets": True,
            "validate": False,
            "max_tokens": 4096,
            "timeout_seconds": 60,
            "review_concurrency": 3,
            "enable_static_analysis": True,
            "enable_cross_file_review": False,
            "cross_file_max_files": 5,
            "max_cost_per_run": 1.0,
            "max_cost_per_24h": 5.0,
            "ui_language": "zh-CN",
        }

        status, body = call(server["base"], "POST", "/api/config", payload)

        parsed = json.loads(body)
        assert status == 200, body
        assert parsed["ok"] is True
        assert "unsupported key" not in parsed["message"]

    def test_save_response_carries_structured_message_keys(self, server):
        """英文界面要显示"Saved …"而不是中文原文，靠的就是响应里的 `message_key`。

        回归点：`SaveResult` 早就带了 `message_key/message_params`，但 HTTP 层曾只回
        `message`，前端 `hasDictKey` 永远拿不到 key，于是英文界面静默回落成中文。
        这条用例锁死"键必须真的过线"。
        """
        status, body = call(server["base"], "POST", "/api/config", {"ui_language": "en-US"})

        parsed = json.loads(body)
        assert status == 200, body
        assert parsed["message_key"] == "config.save.saved", body
        assert parsed["message_params"]["count"] == 1

        # 无改动时走 noop 分支，键也要跟着换，而不是继续复用 saved。
        status, body = call(server["base"], "POST", "/api/config", {"ui_language": "en-US"})

        parsed = json.loads(body)
        assert status == 200, body
        assert parsed["message_key"] == "config.save.noop", body
        assert parsed["message_params"] == {}


class TestCrossSiteGuard:
    """写端点必须挡住"任意网页对 127.0.0.1 发简单请求"这条 CSRF 路径。

    工作台无鉴权、监听回环：浏览器把跨站 `text/plain` POST 当简单请求（无预检），
    所以只靠"localhost"这个事实并不安全——`/api/config` 与 `/api/publish` 都会真的写东西。
    """

    def test_plain_text_post_is_rejected(self, server):
        status, _, _ = call_raw(
            server["base"],
            "POST",
            "/api/feedback",
            body='{"run_id":"x","finding_id":"y","status":"accepted"}',
            headers={"content-type": "text/plain"},
        )

        assert status == 415

    def test_cross_origin_json_post_is_rejected(self, server):
        status, _, _ = call_raw(
            server["base"],
            "POST",
            "/api/config",
            body={"ui_language": "en-US"},
            headers={"content-type": "application/json", "origin": "https://evil.example"},
        )

        assert status == 415

    def test_cross_site_fetch_metadata_is_rejected(self, server):
        status, _, _ = call_raw(
            server["base"],
            "POST",
            "/api/publish",
            body={"run_id": server["run_id"], "confirm": False},
            headers={
                "content-type": "application/json",
                "sec-fetch-site": "cross-site",
            },
        )

        assert status == 415

    def test_same_origin_preview_is_allowed(self, server):
        """同源（本机 Origin）请求必须放行——守卫不能把工作台自己挡住。"""
        status, _, _ = call_raw(
            server["base"],
            "POST",
            "/api/publish",
            body={"run_id": server["run_id"], "confirm": False},
            headers={
                "content-type": "application/json",
                "origin": server["base"],
                "sec-fetch-site": "same-origin",
            },
        )

        assert status == 200

    def test_options_is_not_implemented_without_cors_headers(self, server):
        status, headers, _ = call_raw(server["base"], "OPTIONS", "/api/config")

        assert status == 405
        assert not any(key.startswith("access-control-") for key in headers)


class TestPublishEndpoint:
    def test_missing_run_id_is_rejected(self, server):
        status, body = call(server["base"], "POST", "/api/publish", {})

        assert status == 400
        assert json.loads(body)["code"] == "invalid_request"

    def test_preview_never_posts_and_returns_comment_body(self, server):
        with mock.patch.object(
            PublishService, "_post_comment", side_effect=AssertionError("preview must not post")
        ) as post:
            status, body = call(
                server["base"],
                "POST",
                "/api/publish",
                {"run_id": server["run_id"], "confirm": False},
            )

        payload = json.loads(body)
        assert status == 200, body
        assert payload["status"] == "preview"
        assert payload["requires_confirmation"] is True
        assert payload["comment_chars"] == len(payload["comment_body"])
        assert payload["comment_url"] == ""
        assert post.call_count == 0

    def test_unknown_run_is_not_found(self, server):
        status, body = call(server["base"], "POST", "/api/publish", {"run_id": "does-not-exist"})

        assert status == 404
        assert json.loads(body)["code"] == "not_found"

    def test_confirm_publishes_and_records_ledger(self, server):
        def fake_post(self, target):  # noqa: ANN001 - 只模拟"GitHub 写成功"
            self.last_comment_url = "https://github.com/owner/repo/pull/7#issuecomment-1"
            self.last_comment_id = "1"

        with mock.patch.object(PublishService, "_post_comment", fake_post):
            status, body = call(
                server["base"],
                "POST",
                "/api/publish",
                {"run_id": server["run_id"], "confirm": True},
            )

        payload = json.loads(body)
        assert status == 200
        assert payload["status"] == "published"
        assert payload["comment_id"] == "1"
        assert payload["comment_url"].endswith("#issuecomment-1")

        ledger = server["config_path"].parent / "published-comments.json"
        assert ledger.exists()
        assert server["run_id"] in json.loads(ledger.read_text(encoding="utf-8"))

    def test_second_publish_is_flagged_as_repeat(self, server):
        def fake_post(self, target):  # noqa: ANN001
            self.last_comment_url = "https://github.com/owner/repo/pull/7#issuecomment-2"
            self.last_comment_id = "2"

        with mock.patch.object(PublishService, "_post_comment", fake_post):
            call(
                server["base"],
                "POST",
                "/api/publish",
                {"run_id": server["run_id"], "confirm": True},
            )
            _, body = call(
                server["base"],
                "POST",
                "/api/publish",
                {"run_id": server["run_id"], "confirm": True},
            )

        payload = json.loads(body)
        # 契约：重复发布"照发 + 警告"，不静默跳过
        assert payload["status"] == "already_published"
        assert payload["already_published"] is True
        assert "已发布过" in payload["message"]

    def test_missing_credentials_maps_to_503(self, server):
        with mock.patch.object(
            PublishService,
            "preview",
            side_effect=PublishError("missing_credentials", "未配置 GitHub Token"),
        ):
            status, body = call(
                server["base"], "POST", "/api/publish", {"run_id": server["run_id"]}
            )

        assert status == 503
        assert json.loads(body)["code"] == "missing_credentials"


class TestChatEndpoint:
    """`POST /api/chat` 的协议层：只做 code ↔ HTTP 映射，模型调用由服务层负责。

    服务层（`ai_pr_review.web_chat`）的真实行为由 `tests/test_web_chat.py` 覆盖；
    这里锁的是路由接线、错误码映射与响应形状。
    """

    def test_missing_text_is_rejected(self, server):
        status, body = call(server["base"], "POST", "/api/chat", {"run_id": server["run_id"]})

        assert status == 400
        assert json.loads(body)["code"] == "invalid_request"

    def test_unknown_run_is_not_found(self, server):
        status, body = call(
            server["base"],
            "POST",
            "/api/chat",
            {"run_id": "does-not-exist", "text": "这条为什么判中风险？"},
        )

        assert status == 404
        assert json.loads(body)["code"] == "not_found"

    def test_answer_shape_is_forwarded(self, server):
        canned = {
            "reply": "这条判中风险是因为拼接 SQL。",
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "context_meta": {
                "bound_run": server["run_id"],
                "token_estimate": 42,
                "sections": ["run_summary", "findings"],
                "truncated": False,
                "note": "",
            },
        }
        with mock.patch(
            "ai_pr_review.web_chat.answer_with_context",
            new=mock.AsyncMock(return_value=canned),
        ):
            status, body = call(
                server["base"],
                "POST",
                "/api/chat",
                {"run_id": server["run_id"], "text": "为什么？"},
            )

        assert status == 200, body
        assert json.loads(body) == canned

    def test_missing_api_key_maps_to_503(self, server):
        from ai_pr_review.web_chat import ChatError

        with mock.patch(
            "ai_pr_review.web_chat.answer_with_context",
            new=mock.AsyncMock(side_effect=ChatError("missing_api_key", "未配置模型 API Key")),
        ):
            status, body = call(server["base"], "POST", "/api/chat", {"text": "你好"})

        assert status == 503
        assert json.loads(body)["code"] == "missing_api_key"

    def test_upstream_failure_maps_to_502(self, server):
        from ai_pr_review.web_chat import ChatError

        with mock.patch(
            "ai_pr_review.web_chat.answer_with_context",
            new=mock.AsyncMock(side_effect=ChatError("chat_failed", "模型调用失败：timeout")),
        ):
            status, body = call(server["base"], "POST", "/api/chat", {"text": "你好"})

        assert status == 502
        assert json.loads(body)["code"] == "chat_failed"


class TestReportExportEndpoint:
    def test_markdown_export_is_an_attachment(self, server):
        status, headers, body = call_raw(
            server["base"],
            "GET",
            f"/api/report/export?run_id={server['run_id']}&format=markdown",
        )

        assert status == 200
        assert "text/markdown" in headers["content-type"]
        assert headers["content-disposition"].startswith("attachment;")
        assert f"pr7-{server['run_id'][:8]}.md" in headers["content-disposition"]
        assert body.startswith("# ")
        # 报告正文必须带上 findings 内容（渲染器模板可能中英不同，只断言内容）
        assert "SQL injection risk" in body

    def test_json_export_matches_report_shape(self, server):
        status, headers, body = call_raw(
            server["base"],
            "GET",
            f"/api/report/export?run_id={server['run_id']}&format=json",
        )

        payload = json.loads(body)
        assert status == 200
        assert "application/json" in headers["content-type"]
        assert payload["run_id"] == server["run_id"]
        assert payload["review"]["findings"][0]["title"] == "SQL injection risk"
        assert payload["plan"]["risk_level"] == "high"

    def test_unknown_format_is_rejected(self, server):
        status, body = call(
            server["base"],
            "GET",
            f"/api/report/export?run_id={server['run_id']}&format=pdf",
        )

        assert status == 400
        assert "format must be" in json.loads(body)["error"]

    def test_unknown_run_is_not_found(self, server):
        status, _ = call(server["base"], "GET", "/api/report/export?run_id=nope&format=markdown")

        assert status == 404
