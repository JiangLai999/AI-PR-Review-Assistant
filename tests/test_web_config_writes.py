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

from ai_pr_review.config import (
    REPO_CONTEXT_MODES,
    REVIEW_REASONING_EFFORTS,
    AppConfig,
    ResultStoreConfig,
)
from ai_pr_review.web_config import (
    EDITABLE_AI_FIELDS,
    EDITABLE_PREFERENCE_FIELDS,
    NUMERIC_FIELD_RANGES,
    PREFERENCE_OPTION_KEYS,
    PREFERENCE_OPTION_LABELS,
    PREFERENCE_VOCABULARIES,
    apply_config_update,
    build_config_view,
)


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


# ----------------------------------------------------------- Phase 2 读侧（ConfigView）


def test_config_view_exposes_preferences_and_options(tmp_path: Path) -> None:
    """冻结契约：`to_dict()` 新增 preferences / options / runtime_profile 三键。

    既有键一个不少（老前端只认这些），偏好的**当前值**来自 `config.preferences`。
    """
    from ai_pr_review.backend.jsonl_server import JsonlBackend

    config = _config()
    # 初值刻意不是各清单的第一项，这样"初值来自 preferences"才可证伪。
    config.preferences.ui_language = "en-US"
    config.preferences.review_reasoning_effort = "high"
    config.preferences.repo_context = "tests"
    target = tmp_path / "config.json"

    view = build_config_view(config, config_path=target).to_dict()

    for key in (
        "config_path",
        "github_token_set",
        "github_token_masked",
        "provider_name",
        "base_url",
        "model",
        "api_format",
        "api_key_set",
        "api_key_masked",
        "settings",
        "available_providers",
    ):
        assert key in view, key

    assert set(view["preferences"]) == set(EDITABLE_PREFERENCE_FIELDS)
    assert view["preferences"] == {
        name: getattr(config.preferences, name) for name in EDITABLE_PREFERENCE_FIELDS
    }
    assert view["preferences"]["ui_language"] == "en-US"
    assert view["preferences"]["review_reasoning_effort"] == "high"

    options = view["options"]
    assert set(options) == set(PREFERENCE_OPTION_KEYS.values()) | {"numeric_ranges"}
    for list_key in PREFERENCE_OPTION_KEYS.values():
        items = options[list_key]
        assert items, list_key
        for item in items:
            assert set(item) == {"value", "label"}
            assert item["value"] and item["label"]

    # 档位不自己推导：与 TUI 后端同一份折算结果（默认 balanced → hybrid）。
    assert view["runtime_profile"] in {"cloud", "local", "hybrid", "custom"}
    config.save(target, save_key=False)
    assert view["runtime_profile"] == JsonlBackend(target).runtime_profile

    config.preferences.hybrid_strategy = "local_only"
    assert build_config_view(config).runtime_profile == "local"


def test_options_values_match_config_constants(tmp_path: Path) -> None:
    """清单的 value 逐项等于 config.py 词表（含顺序），label 不与 TUI 漂移。"""
    from ai_pr_review.backend.jsonl_server import JsonlBackend

    view = build_config_view(_config()).to_dict()
    options = view["options"]

    for name, list_key in PREFERENCE_OPTION_KEYS.items():
        assert [item["value"] for item in options[list_key]] == list(
            PREFERENCE_VOCABULARIES[name]
        ), list_key
    # 顺序敏感的两项：config.py 是唯一真相源，改顺序必须原样透传给前端。
    assert [item["value"] for item in options["repo_contexts"]] == list(REPO_CONTEXT_MODES)
    assert [item["value"] for item in options["review_efforts"]] == list(REVIEW_REASONING_EFFORTS)

    tui = JsonlBackend(tmp_path / "config.json")._setup_options()
    tui_blocks = {
        "ui_languages": tui["ui_languages"],
        "output_formats": tui["output_formats"],
        "chat_layouts": tui["chat_layouts"],
        "workbench_modes": tui["workbench_modes"],
        "repo_contexts": tui["repo_context"]["options"],
        "review_efforts": tui["review_reasoning_effort"]["options"],
    }
    for list_key, items in tui_blocks.items():
        tui_labels = {item["value"]: item["label"] for item in items}
        web_labels = {item["value"]: item["label"] for item in options[list_key]}
        assert set(web_labels) == set(tui_labels), list_key
        for value, label in web_labels.items():
            if list_key == "workbench_modes":
                # Web 用冻结契约的短文案；TUI 那份多带 TUI 专属快捷键提示
                # （「Alt+W 收起」），照搬进设置页只会误导鼠标用户。
                assert tui_labels[value].startswith(label), value
            else:
                assert label == tui_labels[value], (list_key, value)


def test_numeric_ranges_are_exposed_and_enforced(tmp_path: Path) -> None:
    """数值范围：同一张表既发给前端渲染 min/max/step，也在后端拒收越界值。"""
    config = _config()
    target = tmp_path / "config.json"

    ranges = build_config_view(config).to_dict()["options"]["numeric_ranges"]

    assert set(ranges) == set(NUMERIC_FIELD_RANGES)
    # 范围表 = 设置页的 6 个数值项（EDITABLE_AI_FIELDS 里的 int/float，
    # 布尔开关与 base_url/model/api_format 这类文本项不进范围表）。
    numeric_fields = {
        name
        for name in EDITABLE_AI_FIELDS
        if isinstance(getattr(config.ai_client, name), (int, float))
        and not isinstance(getattr(config.ai_client, name), bool)
    }
    assert set(NUMERIC_FIELD_RANGES) == numeric_fields
    assert ranges["max_tokens"] == {"min": 1, "max": 128000, "step": 1}
    for name, bounds in ranges.items():
        assert bounds["min"] <= bounds["max"], name
        assert bounds["step"] > 0, name

    out_of_range = (
        ("max_tokens", 0),
        ("timeout_seconds", 4),
        ("review_concurrency", 99),
        ("cross_file_max_files", 0),
        ("max_cost_per_run", -1),
        ("max_cost_per_24h", 1001),
    )
    for name, bad in out_of_range:
        bounds = NUMERIC_FIELD_RANGES[name]
        result = apply_config_update(config, {name: bad}, config_path=target)

        assert result.ok is False, (name, bad, result.message)
        assert result.message.startswith(f"invalid value for {name}"), result.message
        assert f"{bounds['min']}~{bounds['max']}" in result.message
        assert result.changed == []
        assert not target.exists(), (name, bad)
    assert config.ai_client.max_tokens == 4096, "被拒的载荷不许改内存"

    for payload in (
        {"max_tokens": 1},
        {"max_tokens": 128000},
        {"timeout_seconds": "30"},
        {"max_cost_per_24h": 1000},
    ):
        result = apply_config_update(config, payload, config_path=target)

        assert result.ok is True, (payload, result.message)
        assert set(payload) <= set(result.changed), (payload, result.changed)

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["ai_client"]["max_tokens"] == 128000
    assert saved["ai_client"]["max_cost_per_24h"] == 1000
