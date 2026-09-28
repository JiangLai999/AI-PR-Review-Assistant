"""凭证诊断、配置读写与审查任务的测试。

这三个模块是 Web 设置页与任务化审查的后端，覆盖重点：

- 凭证诊断必须区分「未配置」与「配置错误」，且永不返回明文密钥；
- 配置写入时密钥留空表示不改动，避免界面回填掩码把真实密钥覆盖掉；
- 审查任务要能取消，且取消后不再继续调用模型。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_pr_review.config import AIClientConfig, AppConfig, ResultStoreConfig
from ai_pr_review.credentials import (
    CredentialReport,
    CredentialStatus,
    check_github,
    check_model,
    collect_status,
    detect_endpoint_owner,
    mask_secret,
)
from ai_pr_review.web_config import apply_config_update, build_config_view

# --------------------------------------------------------------------- 凭证


class TestMasking:
    def test_empty_stays_empty(self):
        assert mask_secret("") == ""
        assert mask_secret(None) == ""

    def test_short_value_is_fully_hidden(self):
        assert mask_secret("abc") == "•••"
        assert "abc" not in mask_secret("abc")

    def test_long_value_keeps_only_edges(self):
        masked = mask_secret("sk-1234567890abcdef")

        assert masked.startswith("sk-1")
        assert masked.endswith("cdef")
        assert "56789" not in masked
        assert len(masked) < len("sk-1234567890abcdef")


class TestEndpointDetection:
    def test_recognises_known_hosts(self):
        assert detect_endpoint_owner("https://api.deepseek.com/v1") == "DeepSeek"
        assert detect_endpoint_owner("https://openrouter.ai/api/v1") == "OpenRouter"

    def test_unknown_host_returns_none(self):
        assert detect_endpoint_owner("https://internal.example.com/v1") is None


class TestGithubCheck:
    def test_missing_token_is_reported_as_unconfigured(self):
        status = check_github("")

        assert status.ok is False
        assert status.configured is False
        assert "未配置" in status.detail
        assert status.fix_hint

    def test_invalid_token_reports_401_with_rotation_hint(self, monkeypatch):
        monkeypatch.setattr(
            "ai_pr_review.credentials._http_json",
            lambda *a, **k: (401, {"message": "Bad credentials"}),
        )

        status = check_github("ghp_invalid")

        assert status.ok is False
        assert status.configured is True
        assert "401" in status.detail
        assert "重新签发" in status.fix_hint

    def test_valid_token_reports_login(self, monkeypatch):
        monkeypatch.setattr(
            "ai_pr_review.credentials._http_json", lambda *a, **k: (200, {"login": "octocat"})
        )

        status = check_github("ghp_ok")

        assert status.ok is True
        assert "octocat" in status.detail


class TestModelCheck:
    def test_missing_key_is_unconfigured(self):
        status = check_model("https://api.deepseek.com/v1", "", "deepseek-flash")

        assert status.ok is False
        assert status.configured is False

    def test_endpoint_mismatch_is_called_out(self, monkeypatch):
        """密钥被端点拒绝时，必须提示可能是端点配错，而不是笼统说"缺少密钥"。"""
        monkeypatch.setattr(
            "ai_pr_review.credentials._http_json",
            lambda *a, **k: (401, {"message": "Invalid API Key"}),
        )

        status = check_model("https://api.deepseek.com/v1", "sk-somekey", "deepseek-flash")

        assert status.ok is False
        assert status.configured is True
        assert "401" in status.detail
        assert "base_url" in status.fix_hint

    def test_model_not_offered_by_endpoint_is_reported(self, monkeypatch):
        monkeypatch.setattr(
            "ai_pr_review.credentials._http_json",
            lambda *a, **k: (200, {"data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]}),
        )

        status = check_model("https://api.deepseek.com/v1", "sk-ok", "gpt-4o")

        assert status.ok is False
        assert "gpt-4o" in status.detail
        assert "deepseek-flash" in status.detail  # 提示实际可用模型

    def test_matching_model_passes(self, monkeypatch):
        monkeypatch.setattr(
            "ai_pr_review.credentials._http_json",
            lambda *a, **k: (200, {"data": [{"id": "deepseek-flash"}]}),
        )

        status = check_model("https://api.deepseek.com/v1", "sk-ok", "deepseek-flash")

        assert status.ok is True
        assert "DeepSeek" in status.detail

    def test_unreachable_endpoint_is_reported(self, monkeypatch):
        monkeypatch.setattr(
            "ai_pr_review.credentials._http_json", lambda *a, **k: (None, {"error": "timeout"})
        )

        status = check_model("https://unreachable.example/v1", "sk-ok", "m")

        assert status.ok is False
        assert "无法连接" in status.detail


class TestCollectStatus:
    def _config(self, **ai_overrides) -> AppConfig:
        config = AppConfig()
        config.result_store = ResultStoreConfig(db_path=":memory:")
        config.github_token = ai_overrides.pop("github_token", "")
        config.ai_client = AIClientConfig(**ai_overrides)
        return config

    def test_local_mode_does_not_probe_network(self, monkeypatch):
        def explode(*args, **kwargs):
            raise AssertionError("probe=False 不应发网络请求")

        monkeypatch.setattr("ai_pr_review.credentials._http_json", explode)
        config = self._config(
            api_key="sk-x",
            base_url="https://api.deepseek.com/v1",
            github_token="ghp_x",
        )

        report = collect_status(config, probe=False)

        assert report.ok is True, "两项都已填写时，本地模式应判定为可用"
        assert all("尚未探测" in item.detail for item in report.items)

    def test_local_mode_marks_missing_as_not_ok(self):
        report = collect_status(self._config(), probe=False)

        assert report.ok is False
        assert all(item.configured is False for item in report.items)

    def test_report_never_contains_plaintext(self, monkeypatch):
        monkeypatch.setattr(
            "ai_pr_review.credentials._http_json", lambda *a, **k: (200, {"login": "u"})
        )
        config = self._config(
            api_key="sk-supersecretvalue",
            base_url="https://api.deepseek.com/v1",
            github_token="ghp_secret",
        )

        payload = json.dumps(collect_status(config, probe=False).to_dict(), ensure_ascii=False)

        assert "sk-supersecretvalue" not in payload
        assert "ghp_secret" not in payload

    def test_report_dataclasses_serialise(self):
        report = CredentialReport(
            items=[CredentialStatus(key="k", label="L", ok=False, detail="d")]
        )

        assert report.to_dict()["ok"] is False
        assert report.to_dict()["items"][0]["key"] == "k"


# --------------------------------------------------------------------- 配置


class TestConfigView:
    def test_view_masks_secrets(self):
        config = AppConfig()
        config.github_token = "ghp_abcdefghijklmnop"
        config.ai_client = AIClientConfig(api_key="sk-abcdefghijklmnop", model="m")

        view = build_config_view(config).to_dict()
        payload = json.dumps(view, ensure_ascii=False)

        assert view["api_key_set"] is True
        assert view["github_token_set"] is True
        assert "sk-abcdefghijklmnop" not in payload
        assert "ghp_abcdefghijklmnop" not in payload

    def test_view_exposes_provider_presets(self):
        view = build_config_view(AppConfig()).to_dict()

        assert view["available_providers"]
        assert any(p["name"] == "deepseek" for p in view["available_providers"])


class TestApplyConfigUpdate:
    def _config(self) -> AppConfig:
        config = AppConfig()
        config.result_store = ResultStoreConfig(db_path=":memory:")
        config.ai_client = AIClientConfig(api_key="sk-existing", model="old-model")
        return config

    def test_blank_key_keeps_existing(self, tmp_path: Path, monkeypatch):
        """界面回填空字符串时必须保留原密钥，而不是清空。"""
        config = self._config()
        monkeypatch.setattr("ai_pr_review.web_config.DEFAULT_CONFIG_PATH", tmp_path / "c.json")

        apply_config_update(config, {"api_key": "", "model": "new-model"})

        assert config.ai_client.api_key == "sk-existing"
        assert config.ai_client.model == "new-model"

    def test_masked_key_is_not_written_back(self, tmp_path: Path, monkeypatch):
        """掩码（••••）不能被当成真实密钥写回。"""
        config = self._config()
        monkeypatch.setattr("ai_pr_review.web_config.DEFAULT_CONFIG_PATH", tmp_path / "c.json")

        apply_config_update(config, {"api_key": "••••••"})

        assert config.ai_client.api_key == "sk-existing"

    def test_new_key_replaces_old(self, tmp_path: Path, monkeypatch):
        config = self._config()
        monkeypatch.setattr("ai_pr_review.web_config.DEFAULT_CONFIG_PATH", tmp_path / "c.json")

        result = apply_config_update(config, {"api_key": "sk-brand-new"})

        assert config.ai_client.api_key == "sk-brand-new"
        assert "api_key" in result.changed

    def test_numeric_field_is_coerced(self, tmp_path: Path, monkeypatch):
        config = self._config()
        monkeypatch.setattr("ai_pr_review.web_config.DEFAULT_CONFIG_PATH", tmp_path / "c.json")

        apply_config_update(config, {"review_concurrency": "4"})

        assert config.ai_client.review_concurrency == 4

    def test_boolean_field_is_coerced(self, tmp_path: Path, monkeypatch):
        config = self._config()
        monkeypatch.setattr("ai_pr_review.web_config.DEFAULT_CONFIG_PATH", tmp_path / "c.json")

        apply_config_update(config, {"enable_cross_file_review": True})

        assert config.ai_client.enable_cross_file_review is True

    def test_provider_preset_fills_endpoint(self, tmp_path: Path, monkeypatch):
        config = self._config()
        config.ai_client.base_url = ""
        monkeypatch.setattr("ai_pr_review.web_config.DEFAULT_CONFIG_PATH", tmp_path / "c.json")

        apply_config_update(config, {"provider_name": "deepseek", "api_key": "sk-x"})

        assert "deepseek" in config.ai_client.base_url

    def test_no_changes_reports_cleanly(self, tmp_path: Path, monkeypatch):
        config = self._config()
        monkeypatch.setattr("ai_pr_review.web_config.DEFAULT_CONFIG_PATH", tmp_path / "c.json")

        result = apply_config_update(config, {})

        assert result.ok is True
        assert result.changed == []

    def test_secrets_are_persisted_when_requested(self, tmp_path: Path, monkeypatch):
        config = self._config()
        target = tmp_path / "c.json"
        monkeypatch.setattr("ai_pr_review.web_config.DEFAULT_CONFIG_PATH", target)

        result = apply_config_update(config, {"api_key": "sk-persist-me"})

        saved = json.loads(target.read_text(encoding="utf-8"))
        assert saved["ai_client"]["api_key"] == "sk-persist-me"
        assert result.save_key_used is True

    def test_secrets_are_omitted_when_not_requested(self, tmp_path: Path, monkeypatch):
        config = self._config()
        target = tmp_path / "c.json"
        monkeypatch.setattr("ai_pr_review.web_config.DEFAULT_CONFIG_PATH", target)

        with pytest.warns(RuntimeWarning, match="save_key=False"):
            apply_config_update(config, {"api_key": "sk-drop-me", "persist_secrets": False})

        saved = json.loads(target.read_text(encoding="utf-8"))
        assert "api_key" not in saved["ai_client"]


# --------------------------------------------------------------------- 任务


class TestReviewJobManager:
    def _manager(self):
        from ai_pr_review.web_jobs import ReviewJobManager

        config = AppConfig()
        config.result_store = ResultStoreConfig(db_path=":memory:")
        return ReviewJobManager(config)

    def test_start_returns_immediately_with_job_id(self, monkeypatch):
        manager = self._manager()
        # 让任务立即结束，避免真的去抓 PR
        monkeypatch.setattr(manager, "_execute", _noop_coro)

        job = manager.start("https://github.com/o/r/pull/1")

        assert job.job_id
        assert job.status in {"queued", "running", "done"}

    def test_cancel_unknown_job_returns_false(self):
        assert self._manager().cancel("nope") is False

    def test_cancel_marks_job(self, monkeypatch):
        manager = self._manager()
        monkeypatch.setattr(manager, "_execute", _blocking_coro)
        job = manager.start("https://github.com/o/r/pull/1")

        assert manager.cancel(job.job_id) is True
        assert job.cancel_requested is True

    def test_cancelling_finished_job_returns_false(self, monkeypatch):
        manager = self._manager()
        monkeypatch.setattr(manager, "_execute", _noop_coro)
        job = manager.start("https://github.com/o/r/pull/1")

        import time

        for _ in range(50):
            if job.status in {"done", "failed", "cancelled"}:
                break
            time.sleep(0.02)

        assert manager.cancel(job.job_id) is False

    def test_subscribe_receives_events(self):
        manager = self._manager()
        job = type("J", (), {})()  # 占位，真正事件由 _emit 触发
        from ai_pr_review.web_jobs import ReviewJob

        real = ReviewJob(job_id="abc", pr_url="u")
        manager._jobs["abc"] = real
        channel = manager.subscribe("abc")

        manager._emit(real, "stage", message="hello")

        payload = json.loads(channel.get_nowait())
        assert payload["event"] == "stage"
        assert payload["message"] == "hello"
        assert payload["job_id"] == "abc"

    def test_unsubscribe_removes_channel(self):
        manager = self._manager()
        from ai_pr_review.web_jobs import ReviewJob

        manager._jobs["x"] = ReviewJob(job_id="x", pr_url="u")
        channel = manager.subscribe("x")
        manager.unsubscribe("x", channel)

        assert manager._subscribers.get("x") is None

    def test_snapshot_progress_is_bounded(self):
        from ai_pr_review.web_jobs import ReviewJob

        job = ReviewJob(job_id="j", pr_url="u", total_files=4, completed_files=2)
        assert job.snapshot()["progress"] == 0.5

        job.completed_files = 99
        assert job.snapshot()["progress"] == 1.0

    def test_snapshot_with_zero_files(self):
        from ai_pr_review.web_jobs import ReviewJob

        assert ReviewJob(job_id="j", pr_url="u").snapshot()["progress"] == 0.0


async def _noop_coro(job) -> None:  # pragma: no cover - 测试辅助
    return None


async def _blocking_coro(job) -> None:  # pragma: no cover - 测试辅助
    import asyncio

    while not job.cancel_requested:
        await asyncio.sleep(0.01)
    from ai_pr_review.services.review_orchestrator import ReviewCancelled

    raise ReviewCancelled()
