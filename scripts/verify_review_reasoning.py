#!/usr/bin/env python
"""真机验证：**review 链路**是否消费思考档位（DeepSeek 云端，最小化调用）。

与 `scripts/verify_deepseek_live.py`（chat 链路四档）互补：这里走的是审查链路
`AIClient.review_code` —— 即 `review_orchestrator` 逐文件调用模型的那唯一入口。

只读审计得到的两个事实决定了场景设计（详见 `docs/review-reasoning-assessment.md`）：

1. `review_code` 调用 provider 时**不传** `reasoning_effort`（`ai_client.py:86-92`）；
2. 但 `structured_output=True` 会让 provider 追加
   `structured_review_params("deepseek", ...)`（`openai.py:391-395`），其内容由能力档案
   给出 `thinking: {"type": "disabled"}`（`model_capabilities.py:32` + `review_policy.py:16`）。
   即：**review 链路并非"没碰思考参数"，而是把思考显式关掉了**。

四个场景（总调用 4 次，每次都是真实 `review_code`，只改 `AIClientConfig.extra_params`
——`_chat_sync` 会把 extra_params 展开进请求体，`openai.py:384`，且 `setdefault`
不允许 policy 覆盖用户显式值）：

| 场景 | extra_params | 想回答的问题 |
|---|---|---|
| `default` | 无 | 现状：请求长什么样、reasoning 是否为 0、答案是否正常 |
| `effort_low_only` | `reasoning_effort=low` | "只加一行 effort"够不够（policy 的 disabled 还在） |
| `think_low` | `thinking=enabled` + `reasoning_effort=low` | 真要把档位接进 review，代价是多少 |
| `think_max` | `thinking=enabled` + `reasoning_effort=max` | 最高档的 token/时长代价与预算风险 |

密钥只从 `DEEPSEEK_API_KEY` 读，**绝不打印、绝不落盘**；除 DeepSeek 端点外不发任何网络请求。
`max_retries=1`：探针要如实暴露"答案被思考挤空"，不允许格式修复重试偷偷多花一次调用。

注意：`extra_params` 在本脚本里是**测量夹具**，用来回答"如果档位接进 review，代价是多少"，
不是推荐把 `extra_params` 当落地入口（落地入口见交付文档 §4.3：偏好字段 + `review_code` 注入 +
预算预留）。理由之一就是本文件 §1 的结论只对 deepseek 家族成立，而落地要覆盖双槽/混合编排
（`hybrid_orchestrator.py:371-377` 会按文件重建 provider 配置）。

用法::

    python scripts/verify_review_reasoning.py
    python scripts/verify_review_reasoning.py --model deepseek-chat --json

退出码：0 = 门禁断言全过；1 = 有门禁断言失败；2 = 环境不可用（无密钥 / 认证失败 / 四场景全部失败）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai_pr_review.config import AIClientConfig  # noqa: E402
from ai_pr_review.services.ai_client import AIClient  # noqa: E402
from ai_pr_review.services.context_builder import FileContext  # noqa: E402
from ai_pr_review.services.exceptions import AIAuthenticationError  # noqa: E402
from ai_pr_review.services.prompt_assembler import PromptAssembler  # noqa: E402

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"

# 最小 patch：一个真实但面窄的缺陷（SQL 拼接 + 未校验输入），足够让审查链路产出
# 结构化结论，又不会把 prompt 撑大（reasoning 对比不受 prompt 长度干扰）。
DEMO_FILE = "demo/user_lookup.py"
DEMO_DIFF = """\
@@ -1,10 +1,12 @@
 import sqlite3

-def find_user(conn, user_id):
-    cur = conn.cursor()
-    cur.execute("SELECT name FROM users WHERE id = ?", (user_id,))
-    return cur.fetchone()
+def find_user(conn, name):
+    cur = conn.cursor()
+    cur.execute("SELECT id FROM users WHERE name = '%s'" % name)
+    return cur.fetchone()
+
+
+def delete_user(conn, name):
+    cur = conn.cursor()
+    cur.execute("DELETE FROM users WHERE name = '%s'" % name)
+    conn.commit()
"""


def log(message: str) -> None:
    print(message, flush=True)


@dataclass
class Scenario:
    """一个 review 调用场景（含它实际发出去的请求与拿回来的答案）。"""

    name: str
    extra_params: dict[str, Any]
    # 实测
    ok: bool = False
    error: str | None = None
    duration_seconds: float = 0.0
    request_keys: dict[str, Any] = field(default_factory=dict)
    # 真实请求体里与思考有关的键（provider 追加的 policy 参数只能在这一层看到）
    wire_keys: dict[str, Any] = field(default_factory=dict)
    reasoning_chars: int = 0
    answer_chars: int = 0
    findings_count: int = 0
    summary_chars: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str | None = None
    provider_calls: int = 0
    reasoning_on_response_field: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def build_prompts() -> tuple[str, str]:
    """用产品自己的 PromptAssembler 造 prompt（含 JSON schema，与线上逐字同源）。"""
    assembler = PromptAssembler(response_language="zh-CN")
    file_context = FileContext(
        file_path=DEMO_FILE,
        language="python",
        diff=DEMO_DIFF,
        diff_with_context=DEMO_DIFF,
        imports=["import sqlite3"],
        functions=[],
        classes=[],
        parse_mode="regex",
    )
    return assembler.build_system_prompt("python"), assembler.build_user_prompt(file_context)


def build_client(key: str, model: str, base_url: str, extra_params: dict[str, Any]) -> AIClient:
    config = AIClientConfig(
        api_key=key,
        provider="deepseek",
        model=model,
        base_url=base_url,
        api_format="openai",
        extra_params=dict(extra_params),
        # max_tokens 保持产品默认 4096 → 触发 `calculate_review_output_budget`
        # （deepseek + 小输入 = 6144，`model_capabilities.py:66-77`），
        # 即候选实现"不预留思考预算"时真正会发出去的额度。
        max_retries=1,
        timeout_seconds=300,
    )
    return AIClient(config=config)


def instrument(client: AIClient) -> list[dict[str, Any]]:
    """只读探针：记录 provider.chat 的 kwargs 与原始响应（请求构造/解析仍走产品代码）。"""
    capture: list[dict[str, Any]] = []
    original = client._provider.chat  # noqa: SLF001 - 探针需要真实调用参数

    async def recording_chat(messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        response = await original(messages, **kwargs)
        capture.append({"kwargs": kwargs, "response": response})
        return response

    client._provider.chat = recording_chat  # type: ignore[method-assign]  # noqa: SLF001
    return capture


# `thinking` / `response_format` 由 provider 内部（`structured_review_params`）追加进请求体，
# 不经过 kwargs——只看 kwargs 会得出"review 没碰思考参数"的错误结论（第一版探针就踩了这个坑）。
# 因此再包一层 `urllib.request.urlopen`，只记录请求体里与本次评估有关的键，不碰 header/正文。
WIRE_CAPTURE: list[dict[str, Any]] = []
WIRE_FIELDS = (
    "model",
    "max_tokens",
    "stream",
    "response_format",
    "thinking",
    "reasoning_effort",
    "temperature",
)


def install_wire_probe() -> None:
    """进程内替换 `urllib.request.urlopen`（脚本退出即失效，不还原也无副作用）。"""
    original = urllib.request.urlopen

    def recording_urlopen(req: Any, *args: Any, **kwargs: Any) -> Any:
        body = getattr(req, "data", None)
        if body:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                WIRE_CAPTURE.append(
                    {key: payload.get(key, "<absent>") for key in WIRE_FIELDS}
                )
        return original(req, *args, **kwargs)

    urllib.request.urlopen = recording_urlopen  # type: ignore[assignment]


def _raw_message(response: Any) -> dict[str, Any]:
    raw = getattr(response, "raw_response", None)
    if not isinstance(raw, dict):
        return {}
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return {}
    message = choices[0].get("message")
    return message if isinstance(message, dict) else {}


def _finish_reason(response: Any) -> str | None:
    raw = getattr(response, "raw_response", None)
    if not isinstance(raw, dict):
        return None
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None
    value = choices[0].get("finish_reason")
    return str(value) if value is not None else None


def fill_from_capture(
    scenario: Scenario, capture: list[dict[str, Any]], wire: list[dict[str, Any]]
) -> None:
    """把最后一次真实请求的 kwargs / 请求体 / 原始响应写进场景（成败两条路径都调用）。"""
    scenario.provider_calls = len(capture)
    if wire:
        scenario.wire_keys = dict(wire[-1])
    if not capture:
        return
    kwargs = capture[-1]["kwargs"]
    response = capture[-1]["response"]
    scenario.request_keys = {
        "max_tokens": kwargs.get("max_tokens"),
        "thinking": kwargs.get("thinking", "<absent>"),
        "reasoning_effort": kwargs.get("reasoning_effort", "<absent>"),
        "structured_output": kwargs.get("structured_output"),
    }
    message = _raw_message(response)
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    scenario.reasoning_chars = len(reasoning) if isinstance(reasoning, str) else 0
    scenario.answer_chars = len(getattr(response, "text", "") or "")
    scenario.prompt_tokens = int(getattr(response, "input_tokens", 0) or 0)
    scenario.completion_tokens = int(getattr(response, "output_tokens", 0) or 0)
    scenario.total_tokens = scenario.prompt_tokens + scenario.completion_tokens
    scenario.finish_reason = _finish_reason(response)
    scenario.reasoning_on_response_field = bool(getattr(response, "reasoning", None))


async def run_scenario(
    scenario: Scenario, key: str, model: str, base_url: str, system_prompt: str, user_prompt: str
) -> Scenario:
    client = build_client(key, model, base_url, scenario.extra_params)
    capture = instrument(client)
    WIRE_CAPTURE.clear()
    started = time.perf_counter()
    try:
        result = await client.review_code(system_prompt, user_prompt)
    except AIAuthenticationError as exc:
        scenario.error = f"auth: {exc}"
    except Exception as exc:  # noqa: BLE001 - 失败也要如实入库（含答案被思考挤空）
        scenario.error = f"{exc.__class__.__name__}: {exc}"
    else:
        scenario.ok = True
        scenario.summary_chars = len(result.summary or "")
        scenario.findings_count = len(result.findings or [])
    finally:
        scenario.duration_seconds = time.perf_counter() - started
        fill_from_capture(scenario, capture, WIRE_CAPTURE)
    return scenario


def _check(name: str, passed: bool, gating: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "gating": gating, "detail": detail}


def evaluate(scenarios: dict[str, Scenario]) -> list[dict[str, Any]]:
    default = scenarios["default"]
    effort_only = scenarios["effort_low_only"]
    think_low = scenarios["think_low"]
    think_max = scenarios["think_max"]
    total_calls = sum(item.provider_calls for item in scenarios.values())

    checks = [
        _check(
            "a. 现状请求体：审查链路显式关闭思考（thinking=disabled，无 reasoning_effort）",
            default.ok
            and default.wire_keys.get("thinking") == {"type": "disabled"}
            and default.wire_keys.get("reasoning_effort") == "<absent>",
            True,
            f"wire={default.wire_keys}, error={default.error}",
        ),
        _check(
            "b. 现状：关闭后 reasoning=0 且答案非空",
            default.ok and default.reasoning_chars == 0 and default.answer_chars > 0,
            True,
            f"reasoning={default.reasoning_chars} chars, answer={default.answer_chars} chars, "
            f"summary={default.summary_chars}, findings={default.findings_count}",
        ),
        _check(
            "c. 只补 reasoning_effort 不足以开启思考（policy 的 disabled 仍在生效）",
            effort_only.ok
            and effort_only.wire_keys.get("reasoning_effort") == "low"
            and effort_only.wire_keys.get("thinking") == {"type": "disabled"}
            and effort_only.reasoning_chars == 0,
            True,
            f"wire={effort_only.wire_keys}, reasoning={effort_only.reasoning_chars} chars",
        ),
        _check(
            "d. thinking=enabled + low：reasoning 与答案都非空",
            think_low.ok
            and think_low.wire_keys.get("thinking") == {"type": "enabled"}
            and think_low.reasoning_chars > 0
            and think_low.answer_chars > 0,
            True,
            f"wire={think_low.wire_keys}, reasoning={think_low.reasoning_chars} chars, "
            f"answer={think_low.answer_chars} chars, summary={think_low.summary_chars}, "
            f"findings={think_low.findings_count}",
        ),
        _check(
            "e. thinking=enabled + max：reasoning 与答案都非空",
            think_max.ok and think_max.reasoning_chars > 0 and think_max.answer_chars > 0,
            True,
            f"wire={think_max.wire_keys}, reasoning={think_max.reasoning_chars} chars, "
            f"answer={think_max.answer_chars} chars, summary={think_max.summary_chars}, "
            f"findings={think_max.findings_count}, finish_reason={think_max.finish_reason}",
        ),
        _check(
            "f. max 档 reasoning > low 档（单次抽样，方向性）",
            think_low.ok and think_max.ok and think_max.reasoning_chars > think_low.reasoning_chars,
            True,
            f"low={think_low.reasoning_chars} < max={think_max.reasoning_chars}",
        ),
        _check(
            "g. 调用预算：每个场景恰好 1 次 provider 调用（无隐藏重试）",
            total_calls == len(scenarios)
            and all(item.provider_calls == 1 for item in scenarios.values()),
            True,
            f"total_provider_calls={total_calls}, per_scenario="
            f"{ {name: item.provider_calls for name, item in scenarios.items()} }",
        ),
    ]
    return checks


def render(summary: dict[str, Any]) -> None:
    log("")
    log("=" * 78)
    log(f"review 链路思考档位真机验证 · DeepSeek · {summary['model']}")
    log("=" * 78)
    header = (
        f"{'场景':<16}{'thinking':<12}{'effort':<8}{'reasoning':>10}"
        f"{'answer':>8}{'compl.tok':>10}{'耗时s':>8}{'finish':>9}"
    )
    log(header)
    for item in summary["scenarios"]:
        thinking = item["wire_keys"].get("thinking", "<absent>")
        thinking = "disabled" if thinking == {"type": "disabled"} else str(thinking)
        thinking = "enabled" if thinking == {"type": "enabled"} else thinking
        log(
            f"{item['name']:<16}{thinking:<12}"
            f"{str(item['wire_keys'].get('reasoning_effort', '-')):<8}"
            f"{item['reasoning_chars']:>10}{item['answer_chars']:>8}"
            f"{item['completion_tokens']:>10}{item['duration_seconds']:>8.1f}"
            f"{str(item['finish_reason']):>9}"
        )
        if item["error"]:
            log(f"{'':<16}error: {item['error']}")
    log("")
    log(f"审查预算：max_tokens={summary['review_max_tokens']}（产品 review 默认口径）")
    log(f"总耗时：{summary['elapsed_seconds']}s · 总调用：{summary['total_provider_calls']}")
    log(
        "ProviderResponse.reasoning 字段非空："
        f"{sum(1 for item in summary['scenarios'] if item['reasoning_on_response_field'])}"
        f"/{len(summary['scenarios'])} 个场景（非流式路径不回填该字段，见交付文档 §6 #2）"
    )
    log("")
    log("断言：")
    for check in summary["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        gate = "门禁" if check["gating"] else "参考"
        log(f"  [{mark}][{gate}] {check['name']}")
        log(f"          {check['detail']}")
    passed = sum(1 for c in summary["checks"] if c["passed"])
    gating_failed = [c["name"] for c in summary["checks"] if c["gating"] and not c["passed"]]
    log("")
    log(f"结论：断言 {passed}/{len(summary['checks'])} 通过；门禁失败 {len(gating_failed)} 条")
    for name in gating_failed:
        log(f"  - {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"DeepSeek 模型名（默认 {DEFAULT_MODEL}）")
    parser.add_argument("--base-url", default="", help="覆盖 base_url（默认取 DEEPSEEK_BASE_URL 或官方）")
    parser.add_argument("--json", action="store_true", help="只输出机器可读 JSON")
    args = parser.parse_args(argv)

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        log("错误：DEEPSEEK_API_KEY 未设置（只从环境变量读取，不落盘）")
        return 2
    base_url = args.base_url.strip() or os.environ.get("DEEPSEEK_BASE_URL", "").strip() or DEFAULT_BASE_URL

    system_prompt, user_prompt = build_prompts()
    install_wire_probe()
    planned = [
        Scenario("default", {}),
        Scenario("effort_low_only", {"reasoning_effort": "low"}),
        Scenario("think_low", {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}),
        Scenario("think_max", {"thinking": {"type": "enabled"}, "reasoning_effort": "max"}),
    ]

    started = time.monotonic()
    results: dict[str, Scenario] = {}
    for index, scenario in enumerate(planned, start=1):
        log(f"[{index}/{len(planned)}] {scenario.name}: extra_params={scenario.extra_params or '{}'} ...")
        done = asyncio.run(
            run_scenario(scenario, key, args.model, base_url, system_prompt, user_prompt)
        )
        results[scenario.name] = done
        log(
            f"    reasoning={done.reasoning_chars} chars, answer={done.answer_chars} chars, "
            f"summary={done.summary_chars}, findings={done.findings_count}, "
            f"completion_tokens={done.completion_tokens}, {done.duration_seconds:.1f}s"
            + (f", error={done.error}" if done.error else "")
        )
        if done.error and ("401" in done.error or "认证" in done.error):
            log("    key 无效或不可用，终止")
            return 2
    if all(item.error for item in results.values()):
        # 四个场景全军覆没 = 环境/模型名问题，不是"档位结论"，按退出码约定报 2。
        log(f"全部场景失败（首个错误：{next(iter(results.values())).error}）——按环境不可用处理")
        return 2

    checks = evaluate(results)
    gating_ok = all(c["passed"] for c in checks if c["gating"])
    summary: dict[str, Any] = {
        "provider": "deepseek",
        "model": args.model,
        # 真实发出去的输出额度（产品 `calculate_review_output_budget` 的结果，不是配置字面量）。
        "review_max_tokens": results["default"].request_keys.get("max_tokens"),
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "total_provider_calls": sum(item.provider_calls for item in results.values()),
        "scenarios": [item.to_json() for item in results.values()],
        "checks": checks,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        render(summary)
    return 0 if gating_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
