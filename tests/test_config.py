"""配置层测试：PreferencesConfig 校验与 AppConfig 读写往返。

覆盖 workbench_mode（审查工作台显示模式）的默认值、非法值回退、旧配置加载、
保存往返，以及快照/导出所读取的 preferences 视图。

另覆盖 claude-route-slots 任务的新增字段：CHAT/REVIEW 双槽路由
（chat_slot / review_slot + resolve_* / sync_review_slot_to_strategy）与
仓库上下文配置项（repo_context 及其三个上限）。

模型规格（`ProviderConfig.set_model_spec` / 取值边界 / 未知键过滤）的用例按设计
`docs/b2b3-wiring-design.md` §4.1-C 归位到本文件（原落在 tests/test_jsonl_backend.py，
理由见 `docs/claude-backend-followup.md` §1）。
"""

from __future__ import annotations

import json
import warnings
from dataclasses import asdict
from pathlib import Path

import pytest

from ai_pr_review.config import (
    CHAT_SLOT_VALUES,
    CONTEXT_WINDOW_RANGE,
    DEFAULT_MODEL_CONTEXT_WINDOW,
    DEFAULT_MODEL_MAX_OUTPUT,
    DEFAULT_REPO_CONTEXT,
    DEFAULT_REPO_CONTEXT_BUDGET_TOKENS,
    DEFAULT_REPO_CONTEXT_MAX_FILES,
    DEFAULT_REPO_CACHE_MAX_MB,
    DEFAULT_WORKBENCH_MODE,
    MAX_OUTPUT_RANGE,
    MODEL_SPEC_SOURCES,
    REPO_CONTEXT_MODES,
    REVIEW_SLOT_VALUES,
    WORKBENCH_MODES,
    AIClientConfig,
    AppConfig,
    ModelProviderConfig,
    PreferencesConfig,
    ProviderConfig,
    ProviderModelConfig,
    filter_dataclass_payload,
    normalize_chat_slot,
    normalize_repo_cache_max_mb,
    normalize_repo_context,
    normalize_repo_context_budget_tokens,
    normalize_repo_context_max_files,
    normalize_review_slot,
    normalize_workbench_mode,
    resolve_chat_slot,
    resolve_review_slot,
    sync_review_slot_to_strategy,
)

# 本任务新增的 6 个 preferences 字段；"旧配置"用例要把它们整体摘掉。
ROUTE_SLOT_KEYS = ("chat_slot", "review_slot")
REPO_CONTEXT_KEYS = (
    "repo_context",
    "repo_context_max_files",
    "repo_context_budget_tokens",
    "repo_cache_max_mb",
)
NEW_PREFERENCE_KEYS = ROUTE_SLOT_KEYS + REPO_CONTEXT_KEYS


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


# ---------------------------------------------------------------------------
# CHAT/REVIEW 双槽路由 + 仓库上下文配置项（任务 claude-route-slots）
# ---------------------------------------------------------------------------


def _preference_warnings(recorded: list) -> list[str]:
    """只看本模块发出的 preferences 告警，过滤掉无关的第三方 warning。"""
    return [str(item.message) for item in recorded if "preferences." in str(item.message)]


def _legacy_config(tmp_path: Path, strategy: str, *, name: str = "config.json") -> AppConfig:
    """加载一份"旧版本"配置：preferences 里完全没有 6 个新字段。

    返回加载结果，并断言旧配置是**静默**加载的（新校验不得让老配置文件报警）。
    """
    config_path = tmp_path / name
    _saved_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    for key in NEW_PREFERENCE_KEYS:
        payload["preferences"].pop(key, None)
    payload["preferences"]["hybrid_strategy"] = strategy
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        loaded = AppConfig.load(config_path)

    assert _preference_warnings(recorded) == []
    return loaded


def test_route_slot_and_repo_context_constants():
    assert CHAT_SLOT_VALUES == ("remote", "local")
    assert REVIEW_SLOT_VALUES == ("remote", "local", "hybrid")
    assert REPO_CONTEXT_MODES == ("off", "tests", "tests+imports")
    assert DEFAULT_REPO_CONTEXT == "tests+imports"


def test_route_slot_and_repo_context_defaults_match_the_plan():
    """6 个新字段的默认值；旧配置文件因此可以无改动加载。"""
    preferences = PreferencesConfig()
    assert preferences.chat_slot == ""  # 空 = 跟随运行模式预设
    assert preferences.review_slot == ""
    assert preferences.repo_context == "tests+imports"
    assert preferences.repo_context_max_files == 3
    assert preferences.repo_context_budget_tokens == 4000
    assert preferences.repo_cache_max_mb == 200
    # AppConfig.from_env() 走同一条构造路径，默认值必须一致。
    from_env = AppConfig.from_env().preferences
    for key in NEW_PREFERENCE_KEYS:
        assert getattr(from_env, key) == getattr(preferences, key), key
    # 既有字段语义未变：默认仍是 balanced。
    assert preferences.hybrid_strategy == "balanced"


def test_new_fields_default_to_valid_values_without_warning():
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        PreferencesConfig()
    assert _preference_warnings(recorded) == []


@pytest.mark.parametrize(
    ("strategy", "expected_chat", "expected_review"),
    [
        ("remote_only", "remote", "remote"),
        ("local_only", "local", "local"),
        ("balanced", "remote", "hybrid"),
    ],
)
def test_legacy_config_derives_slots_from_strategy(
    tmp_path: Path, strategy: str, expected_chat: str, expected_review: str
):
    """旧配置不含新字段：三种运行模式预设的等价映射（方案 §3.4）。"""
    loaded = _legacy_config(tmp_path, strategy)

    assert loaded.preferences.chat_slot == ""  # 旧配置保持空 = 跟随预设
    assert loaded.preferences.review_slot == ""
    assert resolve_chat_slot(loaded) == expected_chat
    assert resolve_review_slot(loaded) == expected_review


@pytest.mark.parametrize(
    ("hybrid_strategy", "expected_chat", "expected_review"),
    [
        ("remote_only", "remote", "remote"),
        ("local_only", "local", "local"),
        ("balanced", "remote", "hybrid"),
        # 未知预设一律远端；空串按"未设置"处理，同样落远端。
        ("quality_first", "remote", "remote"),
        ("cost_optimized", "remote", "remote"),
        ("offline", "remote", "remote"),
        ("", "remote", "remote"),
        ("unknown", "remote", "remote"),
    ],
)
def test_empty_slots_follow_preset_without_warning(
    hybrid_strategy: str, expected_chat: str, expected_review: str
):
    """空槽位是合法默认值（跟随预设），不是非法值——不得告警。"""
    config = AppConfig.from_env()
    config.preferences.hybrid_strategy = hybrid_strategy

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        assert resolve_chat_slot(config) == expected_chat
        assert resolve_review_slot(config) == expected_review

    assert _preference_warnings(recorded) == []


@pytest.mark.parametrize(
    ("chat_slot", "review_slot", "strategy", "expected_chat", "expected_review"),
    [
        # 显式槽位优先于预设推导，两个槽互不干扰（方案 §2.1 组合矩阵）。
        ("local", "", "remote_only", "local", "remote"),
        ("", "local", "remote_only", "remote", "local"),
        ("remote", "", "local_only", "remote", "local"),
        ("", "remote", "local_only", "local", "remote"),
        ("remote", "local", "balanced", "remote", "local"),
        ("local", "remote", "balanced", "local", "remote"),
        ("", "hybrid", "remote_only", "remote", "hybrid"),
        ("local", "local", "remote_only", "local", "local"),
        ("remote", "remote", "local_only", "remote", "remote"),
        ("local", "hybrid", "local_only", "local", "hybrid"),
    ],
)
def test_explicit_slots_win_over_strategy_derivation(
    chat_slot: str,
    review_slot: str,
    strategy: str,
    expected_chat: str,
    expected_review: str,
):
    config = AppConfig.from_env()
    config.preferences.chat_slot = chat_slot
    config.preferences.review_slot = review_slot
    config.preferences.hybrid_strategy = strategy

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        assert resolve_chat_slot(config) == expected_chat
        assert resolve_review_slot(config) == expected_review

    assert _preference_warnings(recorded) == []


def test_chat_local_with_remote_only_strategy_is_the_configured_combination():
    """组合 3（隐私 + 质量）：聊天走本地、审查走云端；旧架构下无法表达。"""
    config = AppConfig.from_env()
    config.preferences.chat_slot = "local"
    config.preferences.hybrid_strategy = "remote_only"

    assert resolve_chat_slot(config) == "local"
    assert resolve_review_slot(config) == "remote"


@pytest.mark.parametrize("raw", [" Remote ", "LOCAL", "Remote", "  local  "])
def test_explicit_slots_normalize_case_and_whitespace(raw: str):
    """与 workbench_mode / hybrid_strategy 一致：手改配置的大小写差异不算非法值。"""
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        preferences = PreferencesConfig(chat_slot=raw, review_slot=raw)
    assert preferences.chat_slot == raw.strip().lower()
    assert preferences.review_slot == raw.strip().lower()
    assert _preference_warnings(recorded) == []


def test_hybrid_is_valid_for_review_but_not_for_chat():
    """混合是审查侧的高级选项；聊天槽只有二选一（方案 §2）。"""
    with pytest.warns(RuntimeWarning, match="chat_slot"):
        preferences = PreferencesConfig(chat_slot="hybrid", review_slot="hybrid")
    assert preferences.chat_slot == ""
    assert preferences.review_slot == "hybrid"


@pytest.mark.parametrize("raw", ["cloud", "hybrid", "auto", 7, True, ["local"]])
def test_invalid_chat_slot_falls_back_at_construction_with_warning(raw):
    """"hybrid" 对聊天槽非法：只告警回退，绝不抛异常。"""
    with pytest.warns(RuntimeWarning, match="chat_slot"):
        preferences = PreferencesConfig(chat_slot=raw)
    assert preferences.chat_slot == ""


@pytest.mark.parametrize("raw", ["cloud", "auto", 7, ["local"]])
def test_invalid_review_slot_falls_back_at_construction_with_warning(raw):
    with pytest.warns(RuntimeWarning, match="review_slot"):
        preferences = PreferencesConfig(review_slot=raw)
    assert preferences.review_slot == ""


def test_invalid_slot_warning_does_not_echo_the_raw_value():
    """配置可能含终端控制字符或误粘贴的密钥：提示里只报字段名与合法取值。"""
    with pytest.warns(RuntimeWarning) as recorded:
        PreferencesConfig(chat_slot="sk-ant-secret-value")
    message = str(recorded[0].message)
    assert "preferences.chat_slot" in message
    assert "sk-ant-secret-value" not in message


@pytest.mark.parametrize("raw", ["cloud", "hybrid", 7])
def test_invalid_slot_in_config_file_falls_back_on_load(tmp_path: Path, raw):
    """坏值写在磁盘上时，加载即回退（与 workbench_mode 的既有行为一致）。"""
    config_path = tmp_path / "config.json"
    _saved_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["preferences"]["chat_slot"] = raw
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="chat_slot"):
        loaded = AppConfig.load(config_path)

    assert loaded.preferences.chat_slot == ""
    assert resolve_chat_slot(loaded) == "remote"  # 回退推导：balanced -> remote


@pytest.mark.parametrize("raw", ["cloud", "auto", 7])
def test_invalid_review_slot_in_config_file_falls_back_on_load(tmp_path: Path, raw):
    config_path = tmp_path / "config.json"
    _saved_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["preferences"]["review_slot"] = raw
    payload["preferences"]["hybrid_strategy"] = "local_only"
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="review_slot"):
        loaded = AppConfig.load(config_path)

    assert loaded.preferences.review_slot == ""
    assert resolve_review_slot(loaded) == "local"  # 回退推导：local_only -> local


@pytest.mark.parametrize(
    ("chat_raw", "review_raw"),
    [
        ("cloud", "cloud"),
        ("hybrid", "cloud"),  # "hybrid" 对聊天槽非法、对审查槽合法
        (7, 7),
        (["local"], ["local"]),
    ],
)
def test_resolve_slots_warn_for_values_assigned_after_construction(chat_raw, review_raw):
    """构造之后再赋值会绕过 __post_init__，resolve_* 必须自己兜底并告警。"""
    config = AppConfig.from_env()
    config.preferences.hybrid_strategy = "local_only"
    config.preferences.chat_slot = chat_raw
    config.preferences.review_slot = review_raw

    with pytest.warns(RuntimeWarning, match="chat_slot"):
        assert resolve_chat_slot(config) == "local"
    with pytest.warns(RuntimeWarning, match="review_slot"):
        assert resolve_review_slot(config) == "local"

    # resolve_* 是只读的：不得顺手改写配置（否则告警会在下一次调用时消失）。
    assert config.preferences.chat_slot == chat_raw
    assert config.preferences.review_slot == review_raw


def test_resolve_slots_warn_once_per_read():
    """归一化后值已合法，同一次读取不会重复告警（构造期 + resolve 只发一次）。"""
    config = AppConfig.from_env()
    config.preferences.chat_slot = "cloud"

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        resolve_chat_slot(config)
        resolve_chat_slot(config)

    assert len([item for item in recorded if "chat_slot" in str(item.message)]) == 2  # 两次读取各一次


@pytest.mark.parametrize("bad_config", [None, {}, object(), PreferencesConfig()])
def test_resolve_slots_never_raise_on_odd_input(bad_config):
    """不抛异常是硬要求：配置坏了也要能进 pr-review config 去修。"""
    assert resolve_chat_slot(bad_config) in {"remote", "local"}
    assert resolve_review_slot(bad_config) in {"remote", "local", "hybrid"}


def test_resolve_slots_accept_a_bare_preferences_object():
    """resolve_* 同时接受 AppConfig 与裸 PreferencesConfig（便于消费方与测试）。"""
    preferences = PreferencesConfig(chat_slot="local", review_slot="hybrid")
    assert resolve_chat_slot(preferences) == "local"
    assert resolve_review_slot(preferences) == "hybrid"


@pytest.mark.parametrize(
    ("review_slot", "expected_strategy"),
    [("remote", "remote_only"), ("local", "local_only"), ("hybrid", "balanced")],
)
def test_sync_review_slot_folds_into_hybrid_strategy(review_slot: str, expected_strategy: str):
    config = AppConfig.from_env()
    config.preferences.review_slot = review_slot
    # 先写一个"错"的预设，确认是被折算覆盖，而不是恰好等于初值。
    config.preferences.hybrid_strategy = (
        "local_only" if expected_strategy != "local_only" else "remote_only"
    )

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        sync_review_slot_to_strategy(config)

    assert config.preferences.hybrid_strategy == expected_strategy
    assert _preference_warnings(recorded) == []


@pytest.mark.parametrize("review_slot", ["", "cloud", "auto", "quality_first"])
def test_sync_review_slot_leaves_strategy_untouched_without_explicit_slot(review_slot: str):
    """review_slot 为空或非法时，hybrid_strategy（唯一事实来源）不得被动过。"""
    config = AppConfig.from_env()
    config.preferences.review_slot = review_slot
    # 故意用非 balanced 的值：折算表里 balanced 是"hybrid"的产物，若用 balanced
    # 做哨兵，"空值也写 balanced" 这类 bug 会与正确实现无法区分（变异检查实测）。
    config.preferences.hybrid_strategy = "remote_only"

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        sync_review_slot_to_strategy(config)

    assert config.preferences.hybrid_strategy == "remote_only"
    # 告警点只在 resolve_review_slot，sync 不重复告警。
    assert _preference_warnings(recorded) == []


def test_sync_review_slot_matches_case_insensitively():
    config = AppConfig.from_env()
    config.preferences.review_slot = " Hybrid "
    config.preferences.hybrid_strategy = "remote_only"

    sync_review_slot_to_strategy(config)

    assert config.preferences.hybrid_strategy == "balanced"


def test_sync_review_slot_does_not_touch_the_preset_twice():
    """幂等：反复折算结果稳定，且不会把 hybrid_strategy 折回去影响 chat 槽。"""
    config = AppConfig.from_env()
    config.preferences.review_slot = "local"

    sync_review_slot_to_strategy(config)
    sync_review_slot_to_strategy(config)

    assert config.preferences.hybrid_strategy == "local_only"
    assert resolve_review_slot(config) == "local"  # 显式槽位仍然优先
    assert resolve_chat_slot(config) == "local"  # local_only 预设 -> 聊天也走本地


def test_sync_then_resolve_round_trips_every_review_slot():
    """折算后重新推导必须回到原槽位（三个合法值都成立）。"""
    for slot in REVIEW_SLOT_VALUES:
        config = AppConfig.from_env()
        config.preferences.review_slot = slot
        sync_review_slot_to_strategy(config)
        assert resolve_review_slot(config) == slot, slot


@pytest.mark.parametrize("value", ["off", "tests", "tests+imports", " Off ", "TESTS"])
def test_repo_context_accepts_supported_values_without_warning(value: str):
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        preferences = PreferencesConfig(repo_context=value)
    assert preferences.repo_context == value.strip().lower()
    assert _preference_warnings(recorded) == []


@pytest.mark.parametrize("raw", ["everything", "", None, True, 7, ["off"]])
def test_repo_context_falls_back_with_warning(raw):
    with pytest.warns(RuntimeWarning, match="repo_context"):
        preferences = PreferencesConfig(repo_context=raw)
    assert preferences.repo_context == DEFAULT_REPO_CONTEXT == "tests+imports"


@pytest.mark.parametrize(("raw", "expected"), [(1, 1), (10, 10), (3, 3), ("7", 7), (5.0, 5)])
def test_repo_context_max_files_accepts_range_without_warning(raw, expected: int):
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        preferences = PreferencesConfig(repo_context_max_files=raw)
    assert preferences.repo_context_max_files == expected
    assert _preference_warnings(recorded) == []


@pytest.mark.parametrize("raw", [0, 11, -1, 3.5, None, "many", True, False, [], 100])
def test_repo_context_max_files_out_of_range_falls_back_with_warning(raw):
    """bool 是 int 的子类，但 True 不是"最大文件数"能表达的意思，按非法值处理。"""
    with pytest.warns(RuntimeWarning, match="repo_context_max_files"):
        preferences = PreferencesConfig(repo_context_max_files=raw)
    assert preferences.repo_context_max_files == DEFAULT_REPO_CONTEXT_MAX_FILES == 3


@pytest.mark.parametrize(
    ("raw", "expected"), [(500, 500), (32000, 32000), (4000, 4000), ("8000", 8000)]
)
def test_repo_context_budget_tokens_accepts_range_without_warning(raw, expected: int):
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        preferences = PreferencesConfig(repo_context_budget_tokens=raw)
    assert preferences.repo_context_budget_tokens == expected
    assert _preference_warnings(recorded) == []


@pytest.mark.parametrize("raw", [499, 32001, 0, -1, 1.5, None, "lots", True])
def test_repo_context_budget_tokens_out_of_range_falls_back_with_warning(raw):
    with pytest.warns(RuntimeWarning, match="repo_context_budget_tokens"):
        preferences = PreferencesConfig(repo_context_budget_tokens=raw)
    assert preferences.repo_context_budget_tokens == DEFAULT_REPO_CONTEXT_BUDGET_TOKENS == 4000


@pytest.mark.parametrize(("raw", "expected"), [(10, 10), (10000, 10000), (200, 200), ("512", 512)])
def test_repo_cache_max_mb_accepts_range_without_warning(raw, expected: int):
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        preferences = PreferencesConfig(repo_cache_max_mb=raw)
    assert preferences.repo_cache_max_mb == expected
    assert _preference_warnings(recorded) == []


@pytest.mark.parametrize("raw", [9, 10001, 0, -5, 2.5, None, "big", True])
def test_repo_cache_max_mb_out_of_range_falls_back_with_warning(raw):
    with pytest.warns(RuntimeWarning, match="repo_cache_max_mb"):
        preferences = PreferencesConfig(repo_cache_max_mb=raw)
    assert preferences.repo_cache_max_mb == DEFAULT_REPO_CACHE_MAX_MB == 200


@pytest.mark.parametrize(
    ("normalizer", "raw", "default"),
    [
        (normalize_chat_slot, "cloud", ""),
        (normalize_review_slot, "cloud", ""),
        (normalize_repo_context, "everything", "tests+imports"),
        (normalize_repo_context_max_files, 99, 3),
        (normalize_repo_context_budget_tokens, 99, 4000),
        (normalize_repo_cache_max_mb, 5, 200),
    ],
)
def test_normalizers_are_independently_callable(normalizer, raw, default):
    """校验逻辑可独立测试，供后续消费方（RepoContextProvider 等）直接复用。"""
    with pytest.warns(RuntimeWarning):
        assert normalizer(raw) == default


def test_repo_context_preferences_load_from_legacy_config_silently(tmp_path: Path):
    """旧配置没有仓库上下文四项时，加载即默认值且不告警。"""
    loaded = _legacy_config(tmp_path, "balanced", name="legacy-repo.json")

    assert loaded.preferences.repo_context == "tests+imports"
    assert loaded.preferences.repo_context_max_files == 3
    assert loaded.preferences.repo_context_budget_tokens == 4000
    assert loaded.preferences.repo_cache_max_mb == 200


def test_route_slot_and_repo_context_fields_survive_save_load_roundtrip(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config = _saved_config(config_path)
    config.preferences.chat_slot = "local"
    config.preferences.review_slot = "remote"
    config.preferences.repo_context = "off"
    config.preferences.repo_context_max_files = 5
    config.preferences.repo_context_budget_tokens = 8000
    config.preferences.repo_cache_max_mb = 500
    config.save(config_path, save_key=True)

    stored = _preferences_of(config_path)
    assert {key: stored[key] for key in NEW_PREFERENCE_KEYS} == {
        "chat_slot": "local",
        "review_slot": "remote",
        "repo_context": "off",
        "repo_context_max_files": 5,
        "repo_context_budget_tokens": 8000,
        "repo_cache_max_mb": 500,
    }

    loaded = AppConfig.load(config_path).preferences
    assert loaded.chat_slot == "local"
    assert loaded.review_slot == "remote"
    assert loaded.repo_context == "off"
    assert loaded.repo_context_max_files == 5
    assert loaded.repo_context_budget_tokens == 8000
    assert loaded.repo_cache_max_mb == 500
    # 既有字段不受影响。
    assert loaded.hybrid_strategy == config.preferences.hybrid_strategy
    assert loaded.workbench_mode == config.preferences.workbench_mode


def test_route_slot_and_repo_context_fields_reach_the_snapshot_views(tmp_path: Path):
    """快照/导出读的是 preferences 的字段视图，6 个字段都必须在其中。"""
    config_path = tmp_path / "config.json"
    config = _saved_config(config_path)
    config.preferences.chat_slot = "remote"
    config.preferences.review_slot = "hybrid"
    config.preferences.repo_context = "tests"
    config.preferences.repo_context_max_files = 4
    config.preferences.repo_context_budget_tokens = 6000
    config.preferences.repo_cache_max_mb = 300
    config.save(config_path, save_key=True)

    # `pr-review config export` 用 __dict__，后端快照逐字段读取。
    view = config.preferences.__dict__
    exported = asdict(PreferencesConfig())
    for key in NEW_PREFERENCE_KEYS:
        assert key in view, key
        assert key in exported, key
    assert view["review_slot"] == "hybrid"

    reloaded = AppConfig.load(config_path).preferences.__dict__
    for key in NEW_PREFERENCE_KEYS:
        assert reloaded[key] == view[key], key


# ---------------------------------------------------------------------------
# 模型规格：写入口、取值边界、未知键过滤（设计 §4.1-C；原在 test_jsonl_backend.py）
# ---------------------------------------------------------------------------


def test_set_model_spec_touches_only_the_target_model() -> None:
    """`ProviderConfig.set_model_spec`：只动目标条目，不动 `default_model` 与别的模型。"""
    provider = ProviderConfig.from_model_provider(ModelProviderConfig.from_name("deepseek"))
    other_before = (
        provider.models["deepseek-v4-pro"].context_window,
        provider.models["deepseek-v4-pro"].max_output,
    )

    assert (
        provider.set_model_spec(
            "deepseek-flash", context_window=1_000_000, max_output=393_216
        )
        is True
    )
    assert (provider.models["deepseek-flash"].context_window) == 1_000_000
    assert (provider.models["deepseek-flash"].max_output) == 393_216
    assert (
        provider.models["deepseek-v4-pro"].context_window,
        provider.models["deepseek-v4-pro"].max_output,
    ) == other_before
    assert provider.default_model == "deepseek-chat"

    # 同值重写不算"发生写入"；两个参数都 None 更不算。
    assert (
        provider.set_model_spec(
            "deepseek-flash", context_window=1_000_000, max_output=393_216
        )
        is False
    )
    assert provider.set_model_spec("deepseek-flash") is False
    # 中转站那种"预设表里没有"的模型名：显式提交规格会新建条目（B3）。
    assert provider.set_model_spec("relay-model", context_window=200_000) is True
    assert provider.models["relay-model"].context_window == 200_000
    assert provider.models["relay-model"].max_output == 4_096


def test_model_spec_bounds_are_sane() -> None:
    """取值与边界只存一份：`config` 的常量就是 `jsonl_server` 校验用的那一份。"""
    from ai_pr_review.backend import jsonl_server

    assert CONTEXT_WINDOW_RANGE == (1_024, 10_000_000)
    assert MAX_OUTPUT_RANGE == (1, 10_000_000)
    assert jsonl_server.CONTEXT_WINDOW_RANGE is CONTEXT_WINDOW_RANGE
    assert jsonl_server.MAX_OUTPUT_RANGE is MAX_OUTPUT_RANGE
    assert jsonl_server.MODEL_SPEC_SOURCES is MODEL_SPEC_SOURCES
    assert MODEL_SPEC_SOURCES == {"models.dev", "cache", "builtin", "unknown"}
    assert jsonl_server.CATALOG_SOURCES == {"models.dev", "cache", "builtin"}
    # 兜底规格与 `ProviderModelConfig` 的字段默认值是同一组数字。
    assert ProviderModelConfig(name="x").context_window == DEFAULT_MODEL_CONTEXT_WINDOW
    assert ProviderModelConfig(name="x").max_output == DEFAULT_MODEL_MAX_OUTPUT


def test_filter_dataclass_payload_is_shared_by_load_and_import(tmp_path: Path) -> None:
    """未知键过滤只有一份实现：加载路径与导入路径（config_entry）行为一致。

    真实场景是"新版本写的配置文件被旧版本读到"：旧代码没有新键的字段，
    `PreferencesConfig(**payload)` 会 `TypeError`，用户连 `pr-review config` 都进不去。
    """
    payload = {
        "output_format": "json",
        "some_future_preference": {"nested": 1},
    }
    filtered = filter_dataclass_payload(PreferencesConfig, payload)
    assert filtered == {"output_format": "json"}
    # 静态方法保留旧名，两处调用同一个实现（config_entry 直接用模块级函数）。
    assert AppConfig._filter_dataclass_payload(PreferencesConfig, payload) == filtered

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"preferences": payload}, ensure_ascii=False), encoding="utf-8"
    )
    loaded = AppConfig.load(config_path)
    assert loaded.preferences.output_format == "json"
