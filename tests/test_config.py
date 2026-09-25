"""配置层测试：PreferencesConfig 校验与 AppConfig 读写往返。

覆盖 workbench_mode（审查工作台显示模式）的默认值、非法值回退、旧配置加载、
保存往返，以及快照/导出所读取的 preferences 视图。
"""

from __future__ import annotations

import json
import warnings
from dataclasses import asdict
from pathlib import Path

import pytest

from ai_pr_review.config import (
    DEFAULT_WORKBENCH_MODE,
    WORKBENCH_MODES,
    AIClientConfig,
    AppConfig,
    PreferencesConfig,
    ProviderConfig,
    normalize_workbench_mode,
)


def _saved_config(config_path: Path) -> AppConfig:
    """落盘一份带真实 provider 的配置，返回内存中的配置对象。"""
    config = AppConfig.from_env()
    config.ai_client = AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.provider = ProviderConfig.from_model_provider(config.ai_client.model_provider)
    config.save(config_path, save_key=True)
    return config


def _preferences_of(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8"))["preferences"]


def test_workbench_mode_defaults_to_auto():
    assert DEFAULT_WORKBENCH_MODE == "auto"
    assert WORKBENCH_MODES == ("auto", "always", "off")
    assert PreferencesConfig().workbench_mode == "auto"
    assert AppConfig.from_env().preferences.workbench_mode == "auto"


@pytest.mark.parametrize("value", ["auto", "always", "off"])
def test_workbench_mode_accepts_supported_values_without_warning(value: str):
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        preferences = PreferencesConfig(workbench_mode=value)
    assert preferences.workbench_mode == value
    assert [item for item in recorded if "workbench_mode" in str(item.message)] == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(" Always ", "always"), ("OFF", "off"), ("Auto", "auto"), ("  off  ", "off")],
)
def test_workbench_mode_normalizes_case_and_whitespace(raw: str, expected: str):
    # 与 hybrid_strategy 等既有字段一致：手工编辑配置带来的大小写/空格差异不该触发回退。
    assert normalize_workbench_mode(raw) == expected
    assert PreferencesConfig(workbench_mode=raw).workbench_mode == expected


@pytest.mark.parametrize("raw", ["sometimes", "", "auto expand", None, 7, True, ["off"]])
def test_workbench_mode_falls_back_to_auto_with_warning(raw):
    # 非法值只回退 + 警告，绝不抛异常：否则旧配置/手改配置会让 CLI 直接起不来。
    with pytest.warns(RuntimeWarning, match="workbench_mode"):
        preferences = PreferencesConfig(workbench_mode=raw)
    assert preferences.workbench_mode == "auto"


def test_load_legacy_config_without_workbench_mode_is_silent(tmp_path: Path):
    config_path = tmp_path / "config.json"
    _saved_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["preferences"].pop("workbench_mode")
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        loaded = AppConfig.load(config_path)

    assert loaded.preferences.workbench_mode == "auto"
    assert [item for item in recorded if "workbench_mode" in str(item.message)] == []


def test_load_invalid_workbench_mode_falls_back_and_keeps_other_settings(tmp_path: Path):
    config_path = tmp_path / "config.json"
    _saved_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["preferences"]["workbench_mode"] = "expanded"
    payload["preferences"]["chat_layout"] = "split"
    payload["preferences"]["ui_language"] = "en-US"
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="workbench_mode"):
        loaded = AppConfig.load(config_path)

    assert loaded.preferences.workbench_mode == "auto"
    assert loaded.preferences.chat_layout == "split"
    assert loaded.preferences.ui_language == "en-US"
    assert loaded.provider.name == "deepseek"


def test_load_ignores_unknown_preference_keys_from_newer_releases(tmp_path: Path):
    config_path = tmp_path / "config.json"
    _saved_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["preferences"]["workbench_mode"] = "off"
    payload["preferences"]["future_flag"] = True
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = AppConfig.load(config_path)

    assert loaded.preferences.workbench_mode == "off"
    assert not hasattr(loaded.preferences, "future_flag")


def test_workbench_mode_survives_save_load_roundtrip(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config = _saved_config(config_path)

    config.preferences.workbench_mode = "off"
    config.save(config_path, save_key=True)

    assert _preferences_of(config_path)["workbench_mode"] == "off"
    assert AppConfig.load(config_path).preferences.workbench_mode == "off"


def test_saved_preferences_view_carries_workbench_mode_for_snapshots(tmp_path: Path):
    """快照/导出构造器读取的是 preferences 的字段视图，字段必须在其中。"""
    config_path = tmp_path / "config.json"
    config = _saved_config(config_path)
    config.preferences.workbench_mode = "always"
    config.save(config_path, save_key=True)

    # `pr-review config export` 用 __dict__，后端快照逐字段读取；两种视图都必须有值。
    assert config.preferences.__dict__["workbench_mode"] == "always"
    assert asdict(PreferencesConfig(workbench_mode="always"))["workbench_mode"] == "always"
    # 重新加载（后端 config.apply / model.apply 之后的状态）仍带得回来。
    assert AppConfig.load(config_path).preferences.__dict__["workbench_mode"] == "always"
