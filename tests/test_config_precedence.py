from __future__ import annotations

import json
from pathlib import Path

import ai_pr_review.config as config_module
from ai_pr_review.config import (
    PROJECT_CONFIG_DIRNAME,
    PROJECT_CONFIG_FILENAME,
    PROJECT_LOCAL_CONFIG_FILENAME,
    AppConfig,
)


def test_personal_save_overrides_project_shared_config(tmp_path: Path, monkeypatch) -> None:
    """Chat settings must persist above a project-shared default.

    Loading order puts the project shared file above the user file. Saving the
    user file therefore used to look successful in the running process and then
    silently revert on the next launch. Personal edits now land in the
    highest-precedence project-local file whenever a project config exists.
    """
    user_config = tmp_path / "user" / "config.json"
    user_config.parent.mkdir()
    user_config.write_text(
        json.dumps({"preferences": {"hybrid_strategy": "remote_only"}}),
        encoding="utf-8",
    )

    project_root = tmp_path / "workspace"
    project_root.mkdir()
    (project_root / ".git").mkdir()
    project_config_dir = project_root / PROJECT_CONFIG_DIRNAME
    project_config_dir.mkdir()
    (project_config_dir / PROJECT_CONFIG_FILENAME).write_text(
        json.dumps(
            {
                "provider": {
                    "name": "deepseek",
                    "display_name": "DeepSeek",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_format": "openai",
                    "default_model": "deepseek-chat",
                    "models": {
                        "deepseek-chat": {
                            "name": "deepseek-chat",
                            "context_window": 32768,
                            "max_output": 4096,
                        }
                    },
                },
                "preferences": {"hybrid_strategy": "balanced"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", user_config)
    monkeypatch.setattr(config_module, "_default_config_path", lambda: user_config)
    monkeypatch.chdir(project_root)

    config = AppConfig.load()
    # The project shared default wins over the user file, as documented.
    assert config.preferences.hybrid_strategy == "balanced"

    config.preferences.hybrid_strategy = "local_only"
    saved_to = config.save(save_key=True)

    assert saved_to == project_config_dir / PROJECT_LOCAL_CONFIG_FILENAME
    reloaded = AppConfig.load()
    assert reloaded.preferences.hybrid_strategy == "local_only"
    assert reloaded._active_provider_config().name == "ollama"


def test_explicit_config_path_still_receives_explicit_save(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.json"
    config = AppConfig.load(explicit)
    config.preferences.hybrid_strategy = "local_only"

    saved_to = config.save()

    assert saved_to == explicit
    assert AppConfig.load(explicit).preferences.hybrid_strategy == "local_only"


# ------------------------------------------------- Web / CLI 配置隔离（Phase 5）


def test_explicit_save_path_beats_the_env_var(tmp_path: Path, monkeypatch) -> None:
    """显式 `path` 必须压过 `AI_PR_REVIEW_CONFIG`（与 load 侧优先级一致）。

    历史 bug：save 侧先看 env，于是"指定了目标却写到别处"。`pr-review serve`
    给 Web 派生独立配置时正好踩中：env 有值时初值会被写回 CLI 配置。
    """
    env_path = tmp_path / "env.json"
    explicit = tmp_path / "explicit.json"
    monkeypatch.setenv("AI_PR_REVIEW_CONFIG", str(env_path))
    config = AppConfig.load(explicit)

    saved_to = config.save(explicit)

    assert saved_to == explicit
    assert explicit.exists()
    assert not env_path.exists()


def test_resolve_web_config_path_derives_a_sibling_file(tmp_path: Path) -> None:
    assert config_module.resolve_web_config_path(tmp_path / "config.json") == (
        tmp_path / "config.web.json"
    )
    assert config_module.resolve_web_config_path(tmp_path / "workspace-config.json") == (
        tmp_path / "workspace-config.web.json"
    )


class TestServeConfigIsolation:
    """`pr-review serve` 只能在 Web 那份配置上动土。"""

    @staticmethod
    def _invoke_serve(monkeypatch, tmp_path: Path, cli_config: Path):
        """跑 `--config <cli_config> serve`，返回 (web_config_path, 传给 web 层的 config)。"""
        from click.testing import CliRunner

        from ai_pr_review.cli import main

        captured: dict[str, object] = {}

        def fake_serve(config, host="127.0.0.1", port=8787, config_path=None):
            captured["config"] = config
            captured["config_path"] = config_path
            captured["output"] = ""

        monkeypatch.setattr("ai_pr_review.web_server.serve", fake_serve)
        # 必须打桩 CLI 侧的 serve 引用，否则真起服务器。
        result = CliRunner().invoke(main, ["--config", str(cli_config), "serve"])
        assert result.exit_code == 0, result.output
        return captured["config_path"], captured["config"], result.output

    def test_first_run_seeds_web_config_and_leaves_cli_config_alone(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        # 用真实 API 构造 CLI 配置（手写 provider JSON 会漏字段，测试会以假错误失败）
        cli_config = tmp_path / "config.json"
        seed = AppConfig.load(cli_config)
        seed.preferences.ui_language = "en-US"
        seed.save(cli_config, save_key=False)
        before = cli_config.read_bytes()

        web_path, config, output = self._invoke_serve(monkeypatch, tmp_path, cli_config)

        assert web_path == tmp_path / "config.web.json"
        assert (tmp_path / "config.web.json").exists(), "首次启动应派生 Web 配置"
        # 派生的是"CLI 实际生效的结果"，所以偏好被带过去
        assert config.preferences.ui_language == "en-US"
        # CLI 那份必须一个字节都没变
        assert cli_config.read_bytes() == before
        assert "config.web.json" in output

    def test_second_run_keeps_web_edits(self, tmp_path: Path, monkeypatch) -> None:
        cli_config = tmp_path / "config.json"
        cli_config.write_text(json.dumps({"preferences": {"ui_language": "en-US"}}), encoding="utf-8")
        web_config = tmp_path / "config.web.json"
        web_config.write_text(
            json.dumps({"preferences": {"ui_language": "zh-CN"}}), encoding="utf-8"
        )

        _, config, output = self._invoke_serve(monkeypatch, tmp_path, cli_config)

        # 已存在就绝不覆盖：Web 侧的改动不能被 CLI 配置"重新派生"冲掉
        assert config.preferences.ui_language == "zh-CN"
        assert "created" not in output

    def test_no_seed_when_cli_config_does_not_exist(self, tmp_path: Path, monkeypatch) -> None:
        """纯 env / 全新机器：不凭空造文件（也就不会把 env 密钥写进磁盘）。"""
        monkeypatch.setenv("AI_PR_REVIEW_CONFIG", str(tmp_path / "env-only.json"))
        monkeypatch.setenv("AI_PR_REVIEW_API_KEY", "sk-env-only-not-a-real-key")
        cli_config = tmp_path / "env-only.json"

        web_path, config, _ = self._invoke_serve(monkeypatch, tmp_path, cli_config)

        assert web_path == tmp_path / "env-only.web.json"
        assert not web_path.exists()
        # 密钥仍然从 env 生效，只是没有第二条落盘副本
        assert config.ai_client.api_key == "sk-env-only-not-a-real-key"

    def test_env_only_secret_is_not_copied_into_the_web_config(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """CLI 文件里没写密钥（靠 env），派生的 Web 配置里也不许出现明文。"""
        cli_config = tmp_path / "config.json"
        cli_config.write_text(
            json.dumps({"preferences": {"ui_language": "en-US"}}), encoding="utf-8"
        )
        monkeypatch.setenv("AI_PR_REVIEW_API_KEY", "sk-env-only-not-a-real-key")

        web_path, _, _ = self._invoke_serve(monkeypatch, tmp_path, cli_config)

        payload = json.loads(Path(web_path).read_text(encoding="utf-8"))
        assert "sk-env-only-not-a-real-key" not in json.dumps(payload)

    def test_file_stored_secret_is_carried_over(self, tmp_path: Path, monkeypatch) -> None:
        """反过来：CLI 文件里本来就存了明文，派生时照样带过去（保持一致体验）。"""
        cli_config = tmp_path / "config.json"
        cli_config.write_text(
            json.dumps({"provider": {"api_key": "sk-stored-in-file"}}), encoding="utf-8"
        )
        monkeypatch.delenv("AI_PR_REVIEW_API_KEY", raising=False)

        web_path, _, _ = self._invoke_serve(monkeypatch, tmp_path, cli_config)

        payload = json.loads(Path(web_path).read_text(encoding="utf-8"))
        assert payload.get("provider", {}).get("api_key") == "sk-stored-in-file"
