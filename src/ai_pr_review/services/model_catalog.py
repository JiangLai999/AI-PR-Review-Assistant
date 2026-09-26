"""models.dev 模型目录：只负责获取和归一化，不写配置、不渲染 UI。

models.dev 的模型字段在 2026-09-26 的评估中确认为
``limit.context`` / ``limit.output`` / ``reasoning_options``；本模块把它们收敛
成稳定的 ``ModelSpec``，失败时返回 ``None``，由调用方继续使用内置预设。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib import request as urllib_request


MODEL_CATALOG_URL = "https://models.dev/api.json"
MODEL_CATALOG_TIMEOUT_SECONDS = 10
MODEL_CATALOG_SOURCE = "models.dev"

# 应用内 provider 名 -> models.dev 顶层 key。映射依据 2026-09-26 对
# https://models.dev/api.json 的只读探测：DeepSeek 是顶层 `deepseek`；
# MiMo 官方端点同时有 `xiaomi` 与 `xiaomi-token-plan-cn`。这里只映射名称，
# 不猜测同一 provider 在不同端点上的参数语义。
PROVIDER_KEY_MAP: dict[str, str] = {
    "anthropic": "anthropic",
    "deepseek": "deepseek",
    "openai": "openai",
    "openrouter": "openrouter",
    "siliconflow": "siliconflow",
    "siliconflow-cn": "siliconflow-cn",
    "moonshot": "moonshotai",
    "moonshotai": "moonshotai",
    "moonshot-cn": "moonshotai-cn",
    "zhipu": "zhipuai",
    "zhipuai": "zhipuai",
    "doubao": "volcengine",
    "qwen": "alibaba",
    "dashscope": "alibaba",
    "xiaomi": "xiaomi",
    "mimo": "xiaomi",
    "xiaomi-token-plan-cn": "xiaomi-token-plan-cn",
    "mimo-token-plan-cn": "xiaomi-token-plan-cn",
    "xiaomi-token-plan-sgp": "xiaomi-token-plan-sgp",
    "xiaomi-token-plan-ams": "xiaomi-token-plan-ams",
    "minimax": "minimax",
    "stepfun": "stepfun",
}


@dataclass(frozen=True)
class ModelSpec:
    """一个模型的远端能力规格。"""

    model_id: str
    provider: str
    context_window: int | None
    max_output: int | None
    reasoning_options: list[dict[str, object]]
    source: str
    fetched_at: datetime


CatalogIndex = dict[tuple[str, str], ModelSpec]


def _provider_key(provider: object) -> str:
    return str(provider or "").strip().casefold()


def _normalized_model_key(model: object) -> str:
    """生成容错查询键：`MiMo v2.5pro` 与 `mimo-v2.5pro` 命中同一条。"""
    raw = str(model or "").strip().casefold()
    return "".join(character for character in raw if character.isalnum() or character in {".", ":"})


def _model_keys(model: object) -> tuple[str, str]:
    raw = str(model or "").strip().casefold()
    return raw, _normalized_model_key(raw)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer():
        return int(value) if value >= 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _string_values(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]


def _copy_reasoning_options(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def lookup_in_index(
    index: CatalogIndex | None, provider: object, model: object
) -> ModelSpec | None:
    """在**已经取到**的索引里查询，绝不触发取数。

    给配置助手的只读出口（`config.snapshot` / `model.status`）用：那些路径必须
    零网络，而 ``ModelCatalog.lookup`` 在冷缓存时会真的发一次请求。
    """
    if index is None:
        return None
    provider_name = _provider_key(provider)
    if not provider_name or not str(model or "").strip():
        return None
    for model_key in _model_keys(model):
        spec = index.get((provider_name, model_key))
        if spec is not None:
            return spec
    return None


class ModelCatalog:
    """按 provider + model 查询 models.dev 的进程内模型目录。"""

    _cache: CatalogIndex | None = None
    _cache_failed = False
    # 上一次真正拿到数据时的来源（B2 的 `source` 判定依据）：
    # 'network' = 本次真的发了 HTTPS；'cache' = 命中进程内缓存；None = 没有可用目录。
    _cache_origin: str | None = None
    _cache_lock = threading.Lock()

    def __init__(self, *, timeout_seconds: int = MODEL_CATALOG_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds

    @classmethod
    def reset_cache(cls) -> None:
        with cls._cache_lock:
            cls._cache = None
            cls._cache_failed = False
            cls._cache_origin = None

    def fetch(self, *, refresh: bool = False) -> CatalogIndex | None:
        """返回索引；进程内成功结果与失败结果都只保留一份。

        缓存失败是为了遵守"同一次运行只拉一次"；用户可以用 ``refresh()``
        在网络恢复后显式重试。HTTP、JSON 或形状错误一律变成 ``None``。
        """
        return self._load(refresh=refresh)

    def refresh(self) -> CatalogIndex | None:
        """忽略进程内缓存，强制重拉一次。"""
        return self._load(refresh=True)

    @classmethod
    def last_load_origin(cls) -> str | None:
        """上一次 ``_load()`` 的数据来源：``'network'`` | ``'cache'`` | ``None``。

        ``None`` 表示没有可用目录（取数失败，或本进程从未取过）——调用方据此回退
        内置预设，不得据此宣称"数据来自缓存"。
        """
        return cls._cache_origin

    def _load(self, *, refresh: bool) -> CatalogIndex | None:
        with ModelCatalog._cache_lock:
            if not refresh:
                if ModelCatalog._cache is not None:
                    ModelCatalog._cache_origin = "cache"
                    return ModelCatalog._cache
                if ModelCatalog._cache_failed:
                    ModelCatalog._cache_origin = None
                    return None
            return self._fetch_from_source()

    def _fetch_from_source(self) -> CatalogIndex | None:
        try:
            request = urllib_request.Request(
                MODEL_CATALOG_URL,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "ai-pr-review-model-catalog",
                },
                method="GET",
            )
            with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._remember_failed_fetch()
            return None

        index = self._build_index(payload)
        if index is None:
            self._remember_failed_fetch()
            return None
        ModelCatalog._cache = index
        ModelCatalog._cache_failed = False
        ModelCatalog._cache_origin = "network"
        return index

    @staticmethod
    def _remember_failed_fetch() -> None:
        ModelCatalog._cache = None
        ModelCatalog._cache_failed = True
        ModelCatalog._cache_origin = None

    def _build_index(self, payload: object) -> CatalogIndex | None:
        if not isinstance(payload, dict):
            return None

        fetched_at = datetime.now(timezone.utc)
        index: CatalogIndex = {}
        for remote_key, provider_payload in payload.items():
            if not isinstance(remote_key, str) or not isinstance(provider_payload, dict):
                continue
            models = provider_payload.get("models")
            if not isinstance(models, dict):
                continue
            for model_id, model_payload in models.items():
                if not isinstance(model_id, str) or not isinstance(model_payload, dict):
                    continue
                limit = model_payload.get("limit")
                limit = limit if isinstance(limit, dict) else {}
                spec = ModelSpec(
                    model_id=model_id,
                    provider=remote_key,
                    context_window=_optional_int(limit.get("context")),
                    max_output=_optional_int(limit.get("output")),
                    reasoning_options=_copy_reasoning_options(
                        model_payload.get("reasoning_options")
                    ),
                    source=MODEL_CATALOG_SOURCE,
                    fetched_at=fetched_at,
                )
                for provider_alias in self._provider_aliases(remote_key):
                    for model_key in _model_keys(model_id):
                        key = (provider_alias, model_key)
                        index.setdefault(key, spec)
        return index

    @staticmethod
    def _provider_aliases(remote_key: str) -> tuple[str, ...]:
        aliases = {remote_key.casefold(), _provider_key(remote_key)}
        for app_name, mapped_key in PROVIDER_KEY_MAP.items():
            if mapped_key == remote_key:
                aliases.add(app_name.casefold())
        return tuple(aliases)

    def lookup(self, provider: str, model: str) -> ModelSpec | None:
        """查找模型；未知 provider/model 或目录不可用时返回 ``None``。"""
        return lookup_in_index(self._load(refresh=False), provider, model)

    def reasoning_summary(self, spec: ModelSpec) -> dict[str, object]:
        """把 models.dev 的 reasoning_options 收敛为可展示的 controls。"""
        controls: list[dict[str, object]] = []
        for raw_option in spec.reasoning_options:
            kind = str(raw_option.get("type", "")).strip().casefold()
            if kind not in {"toggle", "effort", "budget_tokens"}:
                continue
            values = _string_values(raw_option.get("values")) if kind == "effort" else None
            minimum = _optional_int(raw_option.get("min")) if kind == "budget_tokens" else None
            controls.append({"kind": kind, "values": values, "min": minimum})
        return {"supported": bool(controls), "controls": controls}
