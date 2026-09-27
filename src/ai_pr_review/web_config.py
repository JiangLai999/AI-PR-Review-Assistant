"""配置读写：供 Web 设置页使用。

安全约定：

1. 读取时**永不返回明文密钥**，只返回是否已配置与掩码。
2. 写入时密钥字段留空表示"保持不变"，而不是"清空" —— 避免界面回填掩码时
   把真实密钥覆盖成 ``••••``。
3. 写入前可选做连通性校验，失败则拒绝落盘并把原因带回界面。
4. 键位与取值都必须"出声"：白名单外的键、词表外的取值一律 ``ok=False``，
   绝不"界面显示保存成功、磁盘却什么都没写"
   （docs/opencode-web-config-fix.md）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_pr_review.config import (
    DEFAULT_CONFIG_PATH,
    REPO_CONTEXT_MODES,
    REVIEW_REASONING_EFFORTS,
    WORKBENCH_MODES,
    AppConfig,
)
from ai_pr_review.credentials import mask_secret

# 界面可编辑的字段白名单。其余配置项不通过设置页修改，避免误改内部参数。
EDITABLE_AI_FIELDS = (
    "base_url",
    "model",
    "api_format",
    "max_tokens",
    "timeout_seconds",
    "review_concurrency",
    "enable_static_analysis",
    "enable_cross_file_review",
    "cross_file_max_files",
    "max_cost_per_run",
    "max_cost_per_24h",
)

# 设置页可写的 preferences 键（一律写 `config.preferences`，见 apply_config_update）。
# `response_language` / `auto_publish_comment` **刻意不在其中**：交互式界面里
# "自动往 GitHub 发评论" 风险过高，Web 不暴露这两个键 —— 提交即 unsupported key。
EDITABLE_PREFERENCE_FIELDS = (
    "ui_language",
    "output_format",
    "chat_layout",
    "workbench_mode",
    "repo_context",
    "review_reasoning_effort",
)

# 偏好取值词表。config.py 拥有的三项直接引用常量，避免第二份清单漂移；
# 另外三项与 jsonl_server._setup_options()（backend/jsonl_server.py:1329-1347）
# 的展示清单保持一致，由 tests/test_web_config_writes.py 的漂移用例锁住。
UI_LANGUAGES = ("zh-CN", "en-US")
OUTPUT_FORMATS = ("terminal", "markdown", "json")
CHAT_LAYOUTS = ("compact", "split", "plain")

PREFERENCE_VOCABULARIES: dict[str, tuple[str, ...]] = {
    "ui_language": UI_LANGUAGES,
    "output_format": OUTPUT_FORMATS,
    "chat_layout": CHAT_LAYOUTS,
    "workbench_mode": WORKBENCH_MODES,
    "repo_context": REPO_CONTEXT_MODES,
    "review_reasoning_effort": REVIEW_REASONING_EFFORTS,
}

# 偏好键 → 设置页下拉清单键。**键名是冻结契约**（web/src/api/types.ts:230-238 的
# `ConfigOptions`），前端按下拉清单是否存在决定"禁用 + 当前后端不支持这一项"，
# 改名会让 6 个下拉集体退回禁用态。
PREFERENCE_OPTION_KEYS: dict[str, str] = {
    "ui_language": "ui_languages",
    "output_format": "output_formats",
    "chat_layout": "chat_layouts",
    "workbench_mode": "workbench_modes",
    "repo_context": "repo_contexts",
    "review_reasoning_effort": "review_efforts",
}

# 下拉展示文案（`{"value","label"}` 里的 label）。**取值的真相源仍是 config.py 的
# 词表**（PREFERENCE_VOCABULARIES），这里只补中文/英文说明：前 4 项抄
# `jsonl_server._setup_options()`（backend/jsonl_server.py:1329-1347），后 2 项抄
# 同文件的 `REPO_CONTEXT_LABELS`（:171-175）/ `REVIEW_REASONING_LABELS`（:187-193）。
# 与 TUI 的文案差异由 tests/test_web_config_writes.py 的漂移用例锁住：
# `workbench_mode` 刻意用短文案（冻结契约的示例值），TUI 那份多带的是 TUI 专属
# 快捷键提示（「Alt+W 收起」），照搬到 Web 设置页只会误导鼠标用户。
PREFERENCE_OPTION_LABELS: dict[str, dict[str, str]] = {
    "ui_language": {"zh-CN": "中文 / Chinese", "en-US": "English"},
    "output_format": {"terminal": "Terminal", "markdown": "Markdown", "json": "JSON"},
    "chat_layout": {
        "compact": "紧凑 / Compact",
        "split": "分栏 / Split",
        "plain": "纯文本 / Plain",
    },
    "workbench_mode": {"auto": "自动 / Auto", "always": "常驻 / Always", "off": "关闭 / Off"},
    "repo_context": {
        "off": "关闭 / Off",
        "tests": "仅测试文件 / Tests only",
        "tests+imports": "测试与依赖 / Tests + imports",
    },
    "review_reasoning_effort": {
        "off": "关闭 / Off（不思考，默认）",
        "low": "低 / Low（预留 4000 思考 tokens）",
        "high": "高 / High（预留 8000 思考 tokens）",
        "max": "最高 / Max（预留 12000；实测约 3.6× 输出 tokens、2.9× 耗时）",
        "auto": "自动 / Auto（不干预，由供应商默认决定）",
    },
}

# 数值项的合法闭区间。**后端校验与 `options.numeric_ranges` 共用这一张表**：
# 校验逻辑读它（apply_config_update），`GET /api/config` 也原样发出去，
# 前端据此渲染 input 的 min/max/step（web/src/pages/SettingsPage.tsx:677-689）——
# 前端不再各存一份数字，"前端允许、后端拒绝"的分叉因此不存在。
# `step` 只服务 UI（不参与后端判定：0.1 步进的浮点用 == 判对齐会踩二进制误差）。
# 取值口径与前端离线契约一致（docs/claude-web-settings-parity.md §5 [5]）；
# 要放宽只能改这张表一处。
NUMERIC_FIELD_RANGES: dict[str, dict[str, float]] = {
    "max_tokens": {"min": 1, "max": 128000, "step": 1},
    "timeout_seconds": {"min": 5, "max": 600, "step": 5},
    "review_concurrency": {"min": 1, "max": 16, "step": 1},
    "cross_file_max_files": {"min": 1, "max": 10, "step": 1},
    "max_cost_per_run": {"min": 0, "max": 100, "step": 0.1},
    "max_cost_per_24h": {"min": 0, "max": 1000, "step": 0.5},
}

# 载荷里的控制键：不是配置字段，但设置页合法地会带上。
CONTROL_PAYLOAD_KEYS = (
    "provider_name",
    "github_token",
    "api_key",
    "persist_secrets",
    "validate",
)

# apply_config_update 接受的**全部**键。`changed` 的语义锚点见函数 docstring：
# 只报"接受 + 落盘读回校验通过"的键，白名单外的键一律 ok=False。
ACCEPTED_PAYLOAD_KEYS = (
    frozenset(EDITABLE_AI_FIELDS)
    | frozenset(EDITABLE_PREFERENCE_FIELDS)
    | frozenset(CONTROL_PAYLOAD_KEYS)
)

# 端点三键：`hybrid_strategy=local_only` 下必须同步写进"当前生效槽位"，
# 否则 save() → _sync_runtime_sections() 会用 Ollama 的值把它们盖回去。
ENDPOINT_FIELDS = ("base_url", "api_format", "model")


class _RuntimeProfileProbe:
    """`JsonlBackend._infer_runtime_profile` 的最小 ``self``。

    那个折算函数（backend/jsonl_server.py:827-837）只读 ``self.config``，而
    `JsonlBackend.__init__` 会建会话存储、事件计数、审查超时等一整套运行态 ——
    设置页只是想问一句"当前哪一档在生效"，不该为它实例化整个 TUI 后端。
    """

    __slots__ = ("config",)

    def __init__(self, config: AppConfig) -> None:
        self.config = config


def resolve_runtime_profile(config: AppConfig) -> str:
    """当前运行档位（cloud / local / hybrid / custom）。

    **复用** `JsonlBackend._infer_runtime_profile`（backend/jsonl_server.py:827-837）
    的折算规则：生效槽位是 Ollama/local → `local`；环境变量覆盖 → `cloud`；
    否则 `ROUTE_PROFILE_BY_STRATEGY[preferences.hybrid_strategy]`（同文件 :156-160）。
    这里不另写一份，也不自己推导 chat_slot / review_slot —— 槽位路由归后端，
    设置页只读展示（`runtime_profile` 是只读 Chip，不接受提交）。
    """
    from ai_pr_review.backend.jsonl_server import JsonlBackend

    return str(JsonlBackend._infer_runtime_profile(_RuntimeProfileProbe(config)))


def preference_values(config: AppConfig) -> dict[str, str]:
    """设置页 6 个可编辑偏好的当前生效值（与 CLI 助手读同一份 `config.preferences`）。"""
    return {
        name: str(getattr(config.preferences, name, "") or "")
        for name in EDITABLE_PREFERENCE_FIELDS
    }


def preference_options() -> dict[str, Any]:
    """6 个下拉的 `{value, label}` 清单 + `numeric_ranges`。

    value 的顺序 = `config.py` 词表顺序（单一真相源），label 见
    `PREFERENCE_OPTION_LABELS`；数值范围原样透出 `NUMERIC_FIELD_RANGES`。
    """
    options: dict[str, Any] = {}
    for name, key in PREFERENCE_OPTION_KEYS.items():
        labels = PREFERENCE_OPTION_LABELS.get(name, {})
        options[key] = [
            {"value": value, "label": labels.get(value, value)}
            for value in PREFERENCE_VOCABULARIES[name]
        ]
    options["numeric_ranges"] = {
        name: dict(bounds) for name, bounds in NUMERIC_FIELD_RANGES.items()
    }
    return options


@dataclass(slots=True)
class ConfigView:
    """脱敏后的配置视图。"""

    config_path: str
    github_token_set: bool
    github_token_masked: str
    provider_name: str
    base_url: str
    model: str
    api_format: str
    api_key_set: bool
    api_key_masked: str
    settings: dict[str, Any] = field(default_factory=dict)
    available_providers: list[dict[str, str]] = field(default_factory=list)
    # Phase 2 读侧三键（键名冻结，web/src/api/types.ts:240-258）：既有键一个不动，
    # 老前端忽略新键即可；缺这三块时设置页整组降级为"当前后端不支持这一项"。
    preferences: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    runtime_profile: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "github_token_set": self.github_token_set,
            "github_token_masked": self.github_token_masked,
            "provider_name": self.provider_name,
            "base_url": self.base_url,
            "model": self.model,
            "api_format": self.api_format,
            "api_key_set": self.api_key_set,
            "api_key_masked": self.api_key_masked,
            "settings": self.settings,
            "available_providers": self.available_providers,
            "preferences": self.preferences,
            "options": self.options,
            "runtime_profile": self.runtime_profile,
        }


def build_config_view(config: AppConfig, *, config_path: Path | None = None) -> ConfigView:
    """构造脱敏配置视图。"""
    ai = config.ai_client
    from ai_pr_review.config import MODEL_PROVIDER_PRESETS

    presets = [
        {
            "name": name,
            "display_name": str(preset.get("display_name", name)),
            "base_url": str(preset.get("base_url", "")),
            "api_format": str(preset.get("api_format", "openai")),
            "default_model": str(preset.get("default_model", "")),
        }
        for name, preset in sorted(MODEL_PROVIDER_PRESETS.items())
    ]

    options = preference_options()

    return ConfigView(
        config_path=str(config_path or DEFAULT_CONFIG_PATH),
        github_token_set=bool((config.github_token or "").strip()),
        github_token_masked=mask_secret(config.github_token),
        provider_name=ai.provider or config.provider.name or "custom",
        base_url=ai.base_url or "",
        model=ai.model or "",
        api_format=ai.api_format or "openai",
        api_key_set=bool((ai.api_key or "").strip()),
        api_key_masked=mask_secret(ai.api_key),
        settings={name: getattr(ai, name) for name in EDITABLE_AI_FIELDS},
        available_providers=presets,
        preferences=preference_values(config),
        options=options,
        runtime_profile=resolve_runtime_profile(config),
    )


@dataclass(slots=True)
class SaveResult:
    ok: bool
    changed: list[str] = field(default_factory=list)
    message: str = ""
    save_key_used: bool = False


def _safe_token(value: object, *, limit: int = 64) -> str:
    """把不可信的键名/取值裁成可安全回显的短串（不回显控制字符）。

    与 ``config._warn_invalid_preference`` 同理由：提交内容可能带着误粘贴的
    密钥或终端控制字符，回显前先去掉不可打印字符并截断。
    """
    text = "".join(ch for ch in str(value or "") if ch.isprintable())
    return text[:limit]


def _read_back_mismatches(config: AppConfig, path: Path, changed: list[str]) -> list[str]:
    """落盘校验：把 `changed` 里可校验的键读回磁盘比对，返回不一致的键。

    只校验 ``ai_client`` / ``preferences`` 两类非密钥字段；``api_key``、
    ``github_token`` 是凭据（不回读），``provider_name`` 落在槽位上、语义分叉，
    三者都不参与校验。
    """
    verifiable = [
        name for name in changed if name in PREFERENCE_VOCABULARIES or name in EDITABLE_AI_FIELDS
    ]
    if not verifiable:
        return []
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # 读不回来就无法证明"保存成功 == 磁盘真实"，按不一致处理。
        return verifiable
    mismatches: list[str] = []
    for name in verifiable:
        if name in PREFERENCE_VOCABULARIES:
            section, expected = "preferences", getattr(config.preferences, name)
        else:
            section, expected = "ai_client", getattr(config.ai_client, name)
        block = saved.get(section)
        if not isinstance(block, dict) or name not in block or block[name] != expected:
            mismatches.append(name)
    return mismatches


def apply_config_update(
    config: AppConfig,
    payload: dict[str, Any],
    *,
    config_path: Path | None = None,
) -> SaveResult:
    """把界面提交的改动写入配置并落盘。

    契约（docs/opencode-web-config-fix.md）：

    - 空字符串的密钥字段视为"不修改"；掩码（``•`` 开头）同样不写回。
    - **键位**：只接受 ``ACCEPTED_PAYLOAD_KEYS``。白名单外的键返回
      ``SaveResult(ok=False, message="unsupported key: <k>")``，
      **不改内存、不落盘**（调用方按 ``ok`` 映射 HTTP 400）。
    - **取值**：preferences 键按 ``PREFERENCE_VOCABULARIES`` 校验，数值键必须
      能转成数字且落在 ``NUMERIC_FIELD_RANGES``（与 ``options.numeric_ranges``
      同一张表，见该常量的注释）内；非法值 ``ok=False, message="invalid value
      for <k>"``（范围外再补一句允许区间，**不回显原值**）。校验全部通过后才
      开始写，``ok=False`` 即"什么都没发生"。
    - ``changed`` 语义 = **被接受（``ACCEPTED_PAYLOAD_KEYS``）且经落盘读回
      校验确实写进去**的键名；``ok=False`` 时恒为空列表。
    - ``base_url``/``model``/``api_format`` 写进**当前生效槽位**：
      ``hybrid_strategy=local_only`` 时生效槽位是 ``local_provider``，
      只写 ``ai_client`` 会在 ``save()`` → ``_sync_runtime_sections()`` 里
      被 Ollama 的值覆盖（缺陷 2）。
    - ``review_reasoning_effort`` 等偏好一律写 ``config.preferences``（缺陷 3）：
      ``_sync_runtime_sections()`` 每次 save 都会用 preferences 覆盖
      ``ai_client.review_reasoning_effort``。
    - 默认保存密钥（`save_key=True`），因为用户是显式在设置页填写的；
      如果调用方不想要，传 ``persist_secrets=False``。
    - `config_path` 可注入：**测试必须传入临时路径**，否则会覆盖真实用户配置。
    """
    target_path = config_path or DEFAULT_CONFIG_PATH
    persist_secrets = bool(payload.get("persist_secrets", True))
    changed: list[str] = []
    ai = config.ai_client

    # ---- 校验：全部通过之前不改内存、不落盘 ----
    unsupported = sorted(str(key) for key in payload if key not in ACCEPTED_PAYLOAD_KEYS)
    if unsupported:
        return SaveResult(
            ok=False,
            message="unsupported key: " + ", ".join(_safe_token(key) for key in unsupported),
        )

    provider_name = str(payload.get("provider_name", "") or "").strip()
    preset: dict[str, Any] | None = None
    if provider_name:
        from ai_pr_review.config import MODEL_PROVIDER_PRESETS

        preset = MODEL_PROVIDER_PRESETS.get(provider_name.lower())
        if preset is None:
            return SaveResult(
                ok=False, message=f"unsupported provider: {_safe_token(provider_name)}"
            )

    coerced_ai: list[tuple[str, Any]] = []
    for name in EDITABLE_AI_FIELDS:
        if name not in payload:
            continue
        value = payload[name]
        if value is None or value == "":
            continue
        current = getattr(ai, name, None)
        if isinstance(current, bool):
            value = bool(value)
        elif isinstance(current, int) and not isinstance(current, bool):
            try:
                value = int(value)
            except (TypeError, ValueError):
                return SaveResult(ok=False, message=f"invalid value for {name}")
        elif isinstance(current, float):
            try:
                value = float(value)
            except (TypeError, ValueError):
                return SaveResult(ok=False, message=f"invalid value for {name}")
        else:
            value = str(value)
        bounds = NUMERIC_FIELD_RANGES.get(name)
        if bounds is not None:
            # 范围判定用与 UI 同一张表：前端渲染的 min/max 就是后端拒收的边界，
            # 不会出现"界面能填、保存被拒"却没人说得清为什么的分叉。
            try:
                in_range = float(bounds["min"]) <= float(value) <= float(bounds["max"])
            except (TypeError, ValueError):
                in_range = False
            if not in_range:
                return SaveResult(
                    ok=False,
                    message=(
                        f"invalid value for {name}：超出允许范围 "
                        f"{bounds['min']}~{bounds['max']}"
                    ),
                )
        if current != value:
            coerced_ai.append((name, value))

    coerced_prefs: list[tuple[str, str]] = []
    for name in EDITABLE_PREFERENCE_FIELDS:
        if name not in payload:
            continue
        raw = payload[name]
        if raw is None or raw == "":
            continue
        candidate = str(raw).strip()
        if name != "ui_language":
            candidate = candidate.lower()
        if candidate not in PREFERENCE_VOCABULARIES[name]:
            options = "、".join(PREFERENCE_VOCABULARIES[name])
            return SaveResult(ok=False, message=f"invalid value for {name}（可选值：{options}）")
        if str(getattr(config.preferences, name, "") or "") != candidate:
            coerced_prefs.append((name, candidate))

    # ---- 应用 ----
    # 供应商预设：选了预设就带上它的 base_url / api_format。
    # 写入目标是**当前生效槽位**：local_only 下生效槽位是 local_provider，
    # 只写云端槽位会被 _sync_runtime_sections() 忽略（写了个寂寞）。
    if provider_name and preset is not None:
        active_slot = config._active_provider_config()
        if preset.get("base_url") and not payload.get("base_url"):
            if ai.base_url != str(preset["base_url"]):
                ai.base_url = str(preset["base_url"])
                changed.append("base_url")
        if preset.get("api_format") and ai.api_format != str(preset["api_format"]):
            ai.api_format = str(preset["api_format"])
            changed.append("api_format")
        display_name = str(preset.get("display_name", provider_name))
        if active_slot.name != provider_name.lower() or active_slot.display_name != display_name:
            active_slot.name = provider_name.lower()
            active_slot.display_name = display_name
            changed.append("provider_name")

    # 普通字段
    for name, value in coerced_ai:
        setattr(ai, name, value)
        changed.append(name)

    # 缺陷 2：显式提交的端点必须同步进生效槽位，否则落盘时被本地槽位的值覆盖。
    # 只同步"确实提交且确实变了"的键；未提交的字段保持生效槽位原值（回落）。
    active_slot = config._active_provider_config()
    if active_slot is not config.provider:
        for name in ENDPOINT_FIELDS:
            if name not in changed:
                continue
            if name == "model":
                if active_slot.default_model != ai.model:
                    active_slot.default_model = str(ai.model)
                    active_slot.ensure_default_model_present()
            elif getattr(active_slot, name) != getattr(ai, name):
                setattr(active_slot, name, getattr(ai, name))

    # 偏好键：一律落 config.preferences（缺陷 3），ai_client 侧由
    # _sync_runtime_sections() 在 save() 里回填，读回时两边一致。
    for name, value in coerced_prefs:
        setattr(config.preferences, name, value)
        changed.append(name)

    # GitHub token：留空表示不改
    github_token = str(payload.get("github_token", "") or "").strip()
    if github_token:
        config.github_token = github_token
        changed.append("github_token")

    # 模型密钥：留空表示不改（掩码回填时不会被误写成 ••••）
    api_key = str(payload.get("api_key", "") or "").strip()
    if api_key and not api_key.startswith("•"):
        ai.api_key = api_key
        config.provider.api_key = api_key
        changed.append("api_key")

    if not changed:
        return SaveResult(ok=True, message="没有需要保存的改动。")

    path = config.save(target_path, save_key=persist_secrets)

    mismatches = _read_back_mismatches(config, path, changed)
    if mismatches:
        return SaveResult(
            ok=False,
            message="落盘校验失败：" + "、".join(mismatches) + "（磁盘值与提交值不一致）",
        )

    return SaveResult(
        ok=True,
        changed=changed,
        message=f"已保存 {len(changed)} 项到 {path.name}。"
        + ("" if persist_secrets else "（未持久化密钥）"),
        save_key_used=persist_secrets,
    )
