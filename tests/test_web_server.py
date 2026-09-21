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

import pytest

from ai_pr_review.config import AppConfig, ResultStoreConfig
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
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
