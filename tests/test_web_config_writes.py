"""回归：Web 设置页配置写入的三个静默缺陷。

对应 docs/opencode-web-config-fix.md：

1. 白名单外的键被静默丢弃（``ok=True, changed=[]``）；
2. ``hybrid_strategy=local_only`` 时提交的 ``base_url``/``model`` 被 Ollama 值覆盖；
3. ``review_reasoning_effort`` 写 ``ai_client`` 落盘仍是 ``off``。

全部用临时 config 目录，不碰用户真实配置；出现的 ``sk-*`` 都是合成值，
测试不读取、不输出任何真实凭据。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_pr_review.config import AppConfig, ResultStoreConfig
from ai_pr_review.web_config import PREFERENCE_VOCABULARIES, apply_config_update


@pytest.fixture(autouse=True)
def _no_env_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """构造配置时不得读到环境变量里的真实凭据与覆盖项。"""
    from ai_pr_review.config import MODEL_PROVIDER_PRESETS

    for preset in MODEL_PROVIDER_PRESETS.values():
        env_var = str(preset.get("env_var", ""))
        if env_var:
            monkeypatch.delenv(env_var, raising=False)
    for name in (
        "GITHUB_TOKEN",
        "AI_PR_REVIEW_PROVIDER",
        "AI_PR_REVIEW_MODEL",
        "AI_PR_REVIEW_BASE_URL",
        "AI_PR_REVIEW_API_FORMAT",
        "AI_PR_REVIEW_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _config() -> AppConfig:
    """干净配置：内存里也不留环境变量带来的密钥。"""
    config = AppConfig()
    config.result_store = ResultStoreConfig(db_path=":memory:")
    config.github_token = ""
    config.pr_fetcher.github_token = ""
    config.ai_client.api_key = ""
    config.provider.api_key = ""
    config.local_provider.api_key = ""
    return config


def test_unknown_key_is_rejected_not_silently_dropped(tmp_path: Path) -> None:
    """缺陷 1：白名单外的键必须报错，而不是 `ok=True, changed=[]`。"""
    config = _config()
    target = tmp_path / "config.json"

    result = apply_config_update(
        config, {"ui_language": "en-US", "nope_unknown": 1}, config_path=target
    )

    assert result.ok is False
    assert result.message == "unsupported key: nope_unknown"
    assert result.changed == []
    assert not target.exists(), "被拒绝的载荷不许落盘"

    accepted = apply_config_update(config, {"ui_language": "en-US"}, config_path=target)

    assert accepted.ok is True
    assert "ui_language" in accepted.changed
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["preferences"]["ui_language"] == "en-US"


def test_ui_language_and_review_effort_persist_and_read_back(tmp_path: Path) -> None:
    """缺陷 3：偏好键必须落 preferences，且落盘后能原样读回。"""
    config = _config()
    target = tmp_path / "config.json"

    result = apply_config_update(
        config,
        {"ui_language": "en-US", "review_reasoning_effort": "high"},
        config_path=target,
    )

    assert result.ok is True
    assert {"ui_language", "review_reasoning_effort"} <= set(result.changed)

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["preferences"]["ui_language"] == "en-US"
    assert saved["preferences"]["review_reasoning_effort"] == "high"
    assert saved["ai_client"]["review_reasoning_effort"] == "high"

    reloaded = AppConfig.load(target)
    assert reloaded.preferences.ui_language == "en-US"
    assert reloaded.preferences.review_reasoning_effort == "high"
    assert reloaded.ai_client.review_reasoning_effort == "high"


def test_local_only_does_not_override_explicit_base_url_and_model(tmp_path: Path) -> None:
    """缺陷 2：local_only 下显式提交的端点/模型必须真的落盘。"""
    config = _config()
    config.preferences.hybrid_strategy = "local_only"
    target = tmp_path / "config.json"
    config.save(target, save_key=True)

    reloaded = AppConfig.load(target)
    assert reloaded.preferences.hybrid_strategy == "local_only"
    assert reloaded.provider.name.lower() not in {"ollama", "local"}, "前置条件：云端槽位非本地"
    cloud_before = (
        reloaded.provider.name,
        reloaded.provider.base_url,
        reloaded.provider.default_model,
    )

    result = apply_config_update(
        reloaded,
        {"base_url": "https://new.example/v1", "model": "new-model"},
        config_path=target,
    )

    assert result.ok is True
    assert "base_url" in result.changed
    assert "model" in result.changed

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["ai_client"]["base_url"] == "https://new.example/v1"
    assert saved["ai_client"]["model"] == "new-model"
    assert saved["local_provider"]["base_url"] == "https://new.example/v1"
    assert saved["local_provider"]["default_model"] == "new-model"
    # 本地提交不得顺手改写云端槽位
    assert (
        saved["provider"]["name"],
        saved["provider"]["base_url"],
        saved["provider"]["default_model"],
    ) == cloud_before

    final = AppConfig.load(target)
    assert final.ai_client.base_url == "https://new.example/v1"
    assert final.ai_client.model == "new-model"


def test_blank_api_key_keeps_existing(tmp_path: Path) -> None:
    """既有语义：掩码/留空 = 不改，且真的写进磁盘。"""
    config = _config()
    config.ai_client.api_key = "sk-test-existing"
    config.provider.api_key = "sk-test-existing"
    target = tmp_path / "config.json"

    result = apply_config_update(config, {"api_key": "", "model": "same-model"}, config_path=target)

    assert result.ok is True
    assert "api_key" not in result.changed
    assert config.ai_client.api_key == "sk-test-existing"
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["ai_client"]["api_key"] == "sk-test-existing"


def test_keys_never_exposed_to_the_web_stay_unsupported(tmp_path: Path) -> None:
    """任务约定：`response_language` / `auto_publish_comment` 不暴露给 Web UI。"""
    config = _config()
    target = tmp_path / "config.json"

    for payload in ({"auto_publish_comment": True}, {"response_language": "en-US"}):
        result = apply_config_update(config, payload, config_path=target)

        assert result.ok is False, payload
        assert result.changed == []
        assert not target.exists(), payload


def test_invalid_preference_value_is_rejected(tmp_path: Path) -> None:
    """词表外的取值必须报错，不能"保存成功"却写了个回退值。"""
    config = _config()
    target = tmp_path / "config.json"

    result = apply_config_update(config, {"ui_language": "klingon"}, config_path=target)

    assert result.ok is False
    assert result.message.startswith("invalid value for ui_language")
    assert result.changed == []
    assert not target.exists()


def test_preference_vocabularies_do_not_drift_from_the_tui(tmp_path: Path) -> None:
    """Web 侧词表必须与 TUI `config.options` 的展示清单逐字一致。

    否则就是第二份会漂移的清单：TUI 拒绝的取值被 Web 收下（或反过来）。
    """
    from ai_pr_review.backend.jsonl_server import JsonlBackend

    options = JsonlBackend(tmp_path / "config.json")._setup_options()

    blocks = {
        "ui_language": options["ui_languages"],
        "output_format": options["output_formats"],
        "chat_layout": options["chat_layouts"],
        "workbench_mode": options["workbench_modes"],
        "repo_context": options["repo_context"]["options"],
        "review_reasoning_effort": options["review_reasoning_effort"]["options"],
    }
    for key, items in blocks.items():
        assert {item["value"] for item in items} == set(PREFERENCE_VOCABULARIES[key]), key
