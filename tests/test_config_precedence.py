from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import ai_pr_review.config as config_module
from ai_pr_review.config import (
    PROJECT_CONFIG_DIRNAME,
    PROJECT_CONFIG_FILENAME,
    PROJECT_LOCAL_CONFIG_FILENAME,
    AppConfig,
)
from ai_pr_review.web_server import ReviewWebHandler


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
        cli_config.write_text(
            json.dumps({"preferences": {"ui_language": "en-US"}}), encoding="utf-8"
        )
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

    def test_web_config_shares_the_cli_result_store(self, tmp_path: Path, monkeypatch) -> None:
        """设置隔离 ≠ 数据隔离：派生出的 Web 配置必须指向 CLI 那份 results.db。

        回归点：Web 配置不在默认位置会触发 `_derived_result_store_default()`，
        把库改成 `config.web.json` 旁边的另一个文件 —— 历史页会突然"清空"。
        """
        cli_config = tmp_path / "config.json"
        seed = AppConfig.load(cli_config)
        seed.preferences.ui_language = "en-US"
        seed.save(cli_config, save_key=False)

        web_path, config, _ = self._invoke_serve(monkeypatch, tmp_path, cli_config)

        cli_db = AppConfig.load(cli_config).result_store.db_path
        assert str(config.result_store.db_path) == str(cli_db)
        persisted = json.loads(Path(web_path).read_text(encoding="utf-8"))
        assert persisted["result_store"]["db_path"] == str(cli_db)


# --------------------------------- 设置页「从 CLI 配置导入」（POST /api/config/import-cli）


def _post(base: str, path: str, body: dict) -> tuple[int, dict]:
    """按浏览器的方式发一次写请求（JSON + 同源），回读 (状态码, 载荷)。"""
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _start_workbench(config_path: Path) -> tuple[str, AppConfig, ThreadingHTTPServer]:
    """按 `pr-review serve` 的装配方式起一个本地工作台，返回 (base_url, 活的配置, server)。

    不直接调 handler 方法：本任务要验的正是 `do_POST` 的路由表、跨站守卫与状态码映射，
    绕过它们等于什么都没测。`config` 是服务真正持有的那个对象 —— "不重启就生效"只能
    靠它来断言。
    """
    config = AppConfig.load(config_path)
    handler = type(
        "ImportCliWebHandler",
        (ReviewWebHandler,),
        {"config": config, "config_path": config_path},
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{httpd.server_address[1]}", config, httpd


def test_cli_config_path_for_inverts_resolve_web_config_path() -> None:
    """反推必须能原样还原派生规则，否则「导入」会写到另一个文件上。"""
    for base in (Path("config.json"), Path("workspace/config.json"), Path("config")):
        web_path = config_module.resolve_web_config_path(base)
        assert config_module.cli_config_path_for(web_path) == base
    # 不是 Web 派生名 = 没有 CLI 侧：必须明说"没有"，让调用方回 404 而不是猜一个文件
    assert config_module.cli_config_path_for(Path("config.json")) is None
    assert config_module.cli_config_path_for(None) is None


def test_import_config_layers_pins_the_shared_result_store(tmp_path: Path) -> None:
    """搬运规则：合并结果 + 钉住库路径 + 密钥只按"源文件本来就有"决定。"""
    cli_config = tmp_path / "config.json"
    seed = AppConfig.load(cli_config)
    seed.preferences.ui_language = "en-US"
    seed.save(cli_config, save_key=False)
    target = tmp_path / "config.web.json"

    imported = config_module.import_config_layers(target, source_path=cli_config)

    assert imported.saved_path == target
    assert imported.config.preferences.ui_language == "en-US"
    # 源文件里没写密钥（这里靠默认值）→ 不该凭空持久化
    assert imported.secrets_persisted is False
    persisted = json.loads(target.read_text(encoding="utf-8"))
    assert persisted["result_store"]["db_path"] == str(
        AppConfig.load(cli_config).result_store.db_path
    )


def test_adopt_config_layers_makes_a_running_config_follow(tmp_path: Path) -> None:
    """整体搬进正在运行的配置：对象引用不变，值与来源一致。"""
    source = AppConfig.load(tmp_path / "config.json")
    source.preferences.ui_language = "en-US"
    source.provider.default_model = "deepseek-v4-pro"
    source._sync_runtime_sections()
    running = AppConfig.load(tmp_path / "config.web.json")
    running.preferences.ui_language = "zh-CN"
    running.result_store.db_path = str(tmp_path / "stale.db")

    config_module.adopt_config_layers(running, source)

    assert running.preferences.ui_language == "en-US"
    assert running.ai_client.model == "deepseek-v4-pro"
    assert running.result_store.db_path == str(source.result_store.db_path)
    # 钉住标记必须一起搬过来，否则下一次 save() 会把库路径当成推导值抹掉
    assert running._explicit_result_store_db_path is True


class TestImportCliConfigEndpoint:
    """设置页的「从 CLI 配置导入」：覆盖 Web 那份，且立刻在当前进程生效。"""

    @pytest.fixture
    def workbench(self, tmp_path: Path):
        web_config = tmp_path / "config.web.json"
        base, config, httpd = _start_workbench(web_config)
        try:
            yield {
                "base": base,
                "cli_config": tmp_path / "config.json",
                "web_config": web_config,
                "config": config,
            }
        finally:
            httpd.shutdown()
            httpd.server_close()

    @staticmethod
    def _seed_cli_config(path: Path, **overrides: object) -> AppConfig:
        """用真实 API 写一份 CLI 配置（手写 provider JSON 会漏字段，测试会以假错误失败）。"""
        config = AppConfig.load(path)
        for name, value in overrides.items():
            setattr(config.preferences, name, value)
        config.save(path, save_key=False)
        return config

    def _import(self, workbench: dict, body: dict) -> tuple[int, dict]:
        return _post(workbench["base"], "/api/config/import-cli", body)

    @pytest.mark.parametrize("body", [{}, {"confirm": False}, {"confirm": "true"}])
    def test_without_a_literal_true_confirm_it_is_rejected(self, workbench, body) -> None:
        """覆盖动作必须有二次确认，且判定在服务端（防误点/脚本）。"""
        workbench["cli_config"].write_text(
            json.dumps({"preferences": {"ui_language": "en-US"}}), encoding="utf-8"
        )

        status, payload = self._import(workbench, body)

        assert status == 400, payload
        assert "error" in payload
        # 拒绝时一个字节都不许落盘
        assert not workbench["web_config"].exists()

    def test_missing_cli_config_is_404_and_creates_nothing(self, workbench) -> None:
        """CLI 侧没有配置文件（纯 env / 全新机器）就没有可导入的来源。"""
        status, payload = self._import(workbench, {"confirm": True})

        assert status == 404, payload
        assert "error" in payload
        assert not workbench["web_config"].exists()

    def test_web_config_without_the_web_suffix_has_no_cli_side(self, tmp_path: Path) -> None:
        """反推不出 CLI 路径时必须 404：宁可不做，也不能猜个文件覆盖。"""
        base, _, httpd = _start_workbench(tmp_path / "config.json")
        try:
            status, payload = _post(base, "/api/config/import-cli", {"confirm": True})
            assert status == 404, payload
            assert "error" in payload
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_import_makes_the_web_config_follow_the_cli_one(self, workbench) -> None:
        seed = self._seed_cli_config(workbench["cli_config"], ui_language="en-US")
        seed.provider.api_key = "sk-stored-in-cli-file"
        seed.ai_client.api_key = "sk-stored-in-cli-file"
        seed.ai_client.model = "deepseek-v4-pro"
        seed.save(workbench["cli_config"], save_key=True)
        cli_before = workbench["cli_config"].read_bytes()

        status, payload = self._import(workbench, {"confirm": True})

        assert status == 200, payload
        assert payload["ok"] is True
        assert payload["imported_from"] == str(workbench["cli_config"])
        # 响应里的视图已经是导入后的值（前端据此刷新整页）
        assert payload["config"]["preferences"]["ui_language"] == "en-US"
        assert payload["config"]["model"] == "deepseek-v4-pro"
        saved = json.loads(workbench["web_config"].read_text(encoding="utf-8"))
        assert saved["preferences"]["ui_language"] == "en-US"
        # 设置隔离 ≠ 数据隔离：库路径被钉住，历史页不会突然"清空"
        assert saved["result_store"]["db_path"] == str(
            AppConfig.load(workbench["cli_config"]).result_store.db_path
        )
        # 导入只动 Web 那份
        assert workbench["cli_config"].read_bytes() == cli_before

    def test_the_running_process_picks_it_up_without_a_restart(self, workbench) -> None:
        self._seed_cli_config(workbench["cli_config"], ui_language="en-US", output_format="json")
        seed = AppConfig.load(workbench["cli_config"])
        seed.ai_client.model = "deepseek-v4-pro"
        seed.save(workbench["cli_config"], save_key=False)

        status, _ = self._import(workbench, {"confirm": True})

        assert status == 200
        live = workbench["config"]
        assert live.preferences.ui_language == "en-US"
        assert live.preferences.output_format == "json"
        assert live.ai_client.model == "deepseek-v4-pro"
        # 内存与磁盘必须一致，否则界面说"已导入"、下一次审查还在用旧配置
        assert (
            json.loads(workbench["web_config"].read_text(encoding="utf-8"))["ai_client"]["model"]
            == "deepseek-v4-pro"
        )

    def test_env_only_secret_is_not_written_to_disk(self, workbench, monkeypatch) -> None:
        """源文件里没写密钥（靠 env）时，导入也不许把 env 密钥落成第二条副本。"""
        monkeypatch.setenv("AI_PR_REVIEW_API_KEY", "sk-env-only-not-a-real-key")
        workbench["cli_config"].write_text(
            json.dumps({"preferences": {"ui_language": "en-US"}}), encoding="utf-8"
        )

        status, payload = self._import(workbench, {"confirm": True})

        assert status == 200, payload
        assert payload["config"]["api_key_set"] is True
        assert "sk-env-only-not-a-real-key" not in workbench["web_config"].read_text(
            encoding="utf-8"
        )

    def test_a_non_preset_provider_name_does_not_fail_the_whole_import(self, workbench) -> None:
        """中转站/自建端点的供应商名不在预设表里：端点照搬，导入不该整单被拒。"""
        workbench["cli_config"].write_text(
            json.dumps(
                {
                    "provider": {
                        "name": "my-proxy",
                        "display_name": "My Proxy",
                        "base_url": "https://proxy.example.com/v1",
                        "api_format": "openai",
                        "default_model": "proxy-model",
                    },
                    "ai_client": {
                        "provider": "my-proxy",
                        "base_url": "https://proxy.example.com/v1",
                        "api_format": "openai",
                        "model": "proxy-model",
                    },
                }
            ),
            encoding="utf-8",
        )

        status, payload = self._import(workbench, {"confirm": True})

        assert status == 200, payload
        assert payload["config"]["base_url"] == "https://proxy.example.com/v1"
        assert payload["config"]["model"] == "proxy-model"
