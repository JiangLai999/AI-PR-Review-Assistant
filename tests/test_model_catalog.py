"""model_catalog 的离线契约测试（HTTP 层全部 stub，不联网）。"""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone
from typing import Any

import pytest

from ai_pr_review.config import PreferencesConfig
from ai_pr_review.services.model_catalog import ModelCatalog, ModelSpec


def models_dev_payload() -> dict[str, Any]:
    return {
        "deepseek": {
            "models": {
                "deepseek-flash": {
                    "id": "deepseek-flash",
                    "reasoning": True,
                    "reasoning_options": [
                        {"type": "toggle"},
                        {"type": "effort", "values": ["low", "high", "max"]},
                    ],
                    "limit": {"context": 1_000_000, "output": 393_216},
                }
            }
        },
        "xiaomi-token-plan-cn": {
            "models": {
                "mimo-v2.5-pro": {
                    "id": "mimo-v2.5-pro",
                    "reasoning_options": [{"type": "toggle"}],
                    "limit": {"context": 1_048_576, "output": 131_072},
                }
            }
        },
        "anthropic": {
            "models": {
                "claude-sonnet-4-5": {
                    "id": "claude-sonnet-4-5",
                    "reasoning_options": [{"type": "budget_tokens", "min": 1024}],
                    "limit": {"context": 1_000_000, "output": 64_000},
                }
            }
        },
    }


def install_payload(monkeypatch: pytest.MonkeyPatch, payload: object) -> dict[str, int]:
    calls = {"urlopen": 0}

    class StubResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://models.dev/api.json"
        assert timeout == 10
        calls["urlopen"] += 1
        return StubResponse()

    monkeypatch.setattr("ai_pr_review.services.model_catalog.urllib_request.urlopen", fake_urlopen)
    return calls


def install_failure(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"urlopen": 0}

    def failing_urlopen(request, timeout):
        calls["urlopen"] += 1
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(
        "ai_pr_review.services.model_catalog.urllib_request.urlopen", failing_urlopen
    )
    return calls


def make_spec(reasoning_options: list[dict[str, Any]]) -> ModelSpec:
    return ModelSpec(
        model_id="fixture-model",
        provider="fixture",
        context_window=128_000,
        max_output=8_192,
        reasoning_options=reasoning_options,
        source="models.dev",
        fetched_at=datetime.now(timezone.utc),
    )


# models.dev 的真实结构片段（2026-09-26 抓取，字段已核对）：DeepSeek 的
# 1M 上下文 / 393216 输出 / low,high,max+toggle，以及 MiMo 的 toggle-only。
# 这三个用例原先直接联网调 fetch()，在无网环境必然失败——补上 stub 才与文件
# 开头的"HTTP 层全部 stub，不联网"承诺一致。
REAL_MODELS_DEV_SNIPPET: dict[str, Any] = {
    "deepseek": {
        "models": {
            "deepseek-flash": {
                "reasoning": True,
                "reasoning_options": [
                    {"type": "toggle"},
                    {"type": "effort", "values": ["low", "high", "max"]},
                ],
                "limit": {"context": 1_000_000, "output": 393_216},
            }
        }
    },
    "xiaomi": {
        "models": {
            "mimo-v2.5-pro": {
                "reasoning": True,
                "reasoning_options": [{"type": "toggle"}],
                "limit": {"context": 1_048_576, "output": 131_072},
            }
        }
    },
    "xiaomi-token-plan-cn": {
        "models": {
            "mimo-v2.5-pro": {
                "reasoning": True,
                "reasoning_options": [{"type": "toggle"}],
                "limit": {"context": 1_048_576, "output": 131_072},
            }
        }
    },
}


@pytest.fixture(autouse=True)
def reset_catalog_cache():
    ModelCatalog.reset_cache()
    yield
    ModelCatalog.reset_cache()


def test_lookup_returns_exact_models_dev_fields(monkeypatch: pytest.MonkeyPatch):
    install_payload(monkeypatch, REAL_MODELS_DEV_SNIPPET)
    catalog = ModelCatalog()
    assert catalog.fetch() is not None

    spec = catalog.lookup("deepseek", "deepseek-flash")
    assert spec is not None
    assert spec.model_id == "deepseek-flash"
    assert spec.provider == "deepseek"
    assert spec.context_window == 1_000_000
    assert spec.max_output == 393_216
    assert spec.source == "models.dev"
    assert spec.fetched_at.tzinfo is timezone.utc

    summary = catalog.reasoning_summary(spec)
    assert summary == {
        "supported": True,
        "controls": [
            {"kind": "toggle", "values": None, "min": None},
            {"kind": "effort", "values": ["low", "high", "max"], "min": None},
        ],
    }


def test_reasoning_summary_normalizes_each_models_dev_shape():
    catalog = ModelCatalog()
    toggle = catalog.reasoning_summary(
        make_spec([{"type": "toggle", "values": ["ignored"], "min": 7}])
    )
    effort_and_budget = catalog.reasoning_summary(
        make_spec(
            [
                {"type": "effort", "values": ["low", "high"], "min": 3},
                {"type": "budget_tokens", "min": "1024"},
                {"type": "future-mode"},
            ]
        )
    )

    assert toggle == {
        "supported": True,
        "controls": [{"kind": "toggle", "values": None, "min": None}],
    }
    assert effort_and_budget == {
        "supported": True,
        "controls": [
            {"kind": "effort", "values": ["low", "high"], "min": None},
            {"kind": "budget_tokens", "values": None, "min": 1024},
        ],
    }


@pytest.mark.parametrize(
    ("provider", "model", "expected_provider"),
    [
        ("xiaomi", "mimo-v2.5-pro", "xiaomi"),
        ("mimo", "mimo-v2.5-pro", "xiaomi"),
        ("xiaomi-token-plan-cn", "mimo-v2.5-pro", "xiaomi-token-plan-cn"),
        ("mimo-token-plan-cn", "mimo-v2.5-pro", "xiaomi-token-plan-cn"),
    ],
)
def test_provider_key_mapping_lookup(
    provider: str,
    model: str,
    expected_provider: str,
    monkeypatch: pytest.MonkeyPatch,
):
    # 修复：原先这里直连网络；现在注入与其它用例同一份真实片段。
    install_payload(monkeypatch, REAL_MODELS_DEV_SNIPPET)
    catalog = ModelCatalog()
    assert catalog.fetch() is not None

    spec = catalog.lookup(provider, model)
    assert spec is not None
    assert spec.provider == expected_provider
    assert spec.context_window == 1_048_576
    assert catalog.reasoning_summary(spec)["supported"] is True


@pytest.mark.parametrize(
    ("payload", "description"),
    [
        ([], "not a dict"),
        ("{}", "json value is a string"),
    ],
)
def test_invalid_payload_returns_none(
    monkeypatch: pytest.MonkeyPatch, payload: object, description: str
):
    assert description
    calls = install_payload(monkeypatch, payload)
    catalog = ModelCatalog()

    assert catalog.fetch() is None
    assert calls["urlopen"] == 1
    assert catalog.lookup("deepseek", "deepseek-flash") is None


def test_network_failure_and_timeout_are_swallowed(monkeypatch: pytest.MonkeyPatch):
    calls = install_failure(monkeypatch)
    catalog = ModelCatalog()

    assert catalog.fetch() is None
    assert calls["urlopen"] == 1
    assert catalog.lookup("deepseek", "deepseek-flash") is None
    assert calls["urlopen"] == 1


def test_unknown_provider_or_model_returns_none_without_guessing(
    monkeypatch: pytest.MonkeyPatch,
):
    install_payload(monkeypatch, REAL_MODELS_DEV_SNIPPET)
    catalog = ModelCatalog()
    assert catalog.fetch() is not None

    assert catalog.lookup("unknown-provider", "deepseek-flash") is None
    assert catalog.lookup("deepseek", "deepseek-unknown") is None
    assert catalog.lookup("deepseek", "  ") is None
    assert catalog.lookup("", "deepseek-flash") is None


def test_repeated_lookups_share_one_process_wide_fetch(monkeypatch: pytest.MonkeyPatch):
    calls = install_payload(monkeypatch, models_dev_payload())
    first = ModelCatalog()
    second = ModelCatalog()

    assert first.lookup("deepseek", "deepseek-flash") is not None
    assert second.lookup("xiaomi-token-plan-cn", "mimo-v2.5-pro") is not None
    assert first.lookup("anthropic", "claude-sonnet-4-5") is not None
    assert calls["urlopen"] == 1


def test_refresh_forces_the_next_network_fetch(monkeypatch: pytest.MonkeyPatch):
    calls = install_payload(monkeypatch, models_dev_payload())
    catalog = ModelCatalog()

    assert catalog.lookup("deepseek", "deepseek-flash") is not None
    assert calls["urlopen"] == 1
    assert catalog.refresh() is not None
    assert calls["urlopen"] == 2


def test_preference_controls_configuration_assistant_fetch():
    assert PreferencesConfig().model_catalog_fetch is True
    assert PreferencesConfig(model_catalog_fetch="false").model_catalog_fetch is False


def test_last_load_origin_reports_network_then_cache(monkeypatch: pytest.MonkeyPatch):
    """B2 的来源判定（docs/DEV_RECORD.md §3.1）：真拉一次，之后如实报缓存。

    配置助手要靠这个把 `source` 标成 models.dev 还是 cache；翻转（"明明没发请求
    却宣称刚拉过"或反之）会让用户对新鲜度产生错误判断。
    """
    install_payload(monkeypatch, REAL_MODELS_DEV_SNIPPET)
    catalog = ModelCatalog()

    assert catalog.fetch() is not None
    assert ModelCatalog.last_load_origin() == "network"

    assert catalog.fetch() is not None
    assert ModelCatalog.last_load_origin() == "cache"

    assert catalog.refresh() is not None
    assert ModelCatalog.last_load_origin() == "network"


def test_failed_fetch_keeps_origin_none(monkeypatch: pytest.MonkeyPatch):
    """取数失败后 `last_load_origin()` 保持 None：绝不谎报"数据来自缓存"。"""
    calls = install_failure(monkeypatch)
    catalog = ModelCatalog()

    assert catalog.fetch() is None
    assert ModelCatalog.last_load_origin() is None
    # 失败同样只发生一次（进程内不重试），来源仍然是"没有目录"。
    assert catalog.fetch() is None
    assert ModelCatalog.last_load_origin() is None
    assert calls["urlopen"] == 1
