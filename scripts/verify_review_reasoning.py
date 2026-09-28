#!/usr/bin/env python
"""真机验证：**review 链路**的思考档位（DeepSeek 云端，最小化调用）。

与 `scripts/verify_deepseek_live.py`（chat 链路四档）互补：这里走的是审查链路
`AIClient.review_code` —— 即 `review_orchestrator` 逐文件调用模型的那唯一入口。

**历史（为什么有两个口径）**：本脚本第一版（任务 `claude-review-reasoning-assess`）测的是
**旧语义**——review 不消费档位，靠 `AIClientConfig.extra_params` 夹具回答"如果把档位接进去，
代价是多少"。第二步（提交 4321852）把档位真正接进 review 后，本脚本的默认口径改成测
**产品入口**（`preferences.review_reasoning_effort` → `AIClientConfig.review_reasoning_effort`，
注入点在 `ai_client.py:_review_reasoning_plan`）；旧夹具一字未动地留在 `--scenario legacy`。

默认 = 两个新场景都跑（**共 7 次真实调用**，本任务预算 ≤8）：

| 场景 | 档位 | prompt | 想回答的问题 |
|---|---|---|---|
| A `levels` | off / low / high / max（产品入口，各 1 次） | 短 diff（≈4.6k 字符） | 四档是否真的生效；off 是否 reasoning≈0；low<high<max 是否单调；token/耗时代价 |
| B `long` | max ×2 + off ×1（产品入口） | **长 diff**（200-400 行 patch，逐文件审查的真实规模） | 思考会不会吃满 `max_tokens` 把答案挤空/截断；预算预留 +12000（受 `max_output` 封顶）够不够；长 prompt 下 off 的基础额度是否升到 8192 |

`--scenario legacy` 保留第一版的四个夹具场景（`default` / `effort_low_only` / `think_low` /
`think_max`）与它们的断言：那是"假设用 extra_params 接档位"的对照实验，不是产品入口，
但两次真机的可比性靠它维持。

密钥只从 `DEEPSEEK_API_KEY` 读，**绝不打印、绝不落盘**；除 DeepSeek 端点外不发任何网络请求。
`max_retries=1`：探针要如实暴露"答案被思考挤空"，不允许格式修复重试偷偷多花一次调用。

用法::

    python scripts/verify_review_reasoning.py                    # 默认：A + B（7 次调用）
    python scripts/verify_review_reasoning.py --scenario levels  # 只跑四档（4 次）
    python scripts/verify_review_reasoning.py --scenario long    # 只跑长 diff 边界（3 次）
    python scripts/verify_review_reasoning.py --scenario legacy  # 旧夹具场景（4 次）
    python scripts/verify_review_reasoning.py --scenario levels --level max      # 单档（1 次）
    python scripts/verify_review_reasoning.py --scenario levels --level low,high,max
    python scripts/verify_review_reasoning.py --scenario levels --prompt long --level low,high,max
                                                # 四档直接跑在长 diff 上（3 次；max 档同时是边界样本）
    python scripts/verify_review_reasoning.py --scenario long --level high --long-samples 1
    python scripts/verify_review_reasoning.py --model deepseek-chat --json

退出码：0 = 门禁断言全过；1 = 有门禁断言失败；2 = 环境不可用（无密钥 / 认证失败 / 场景全部失败）。
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
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

from ai_pr_review.config import (  # noqa: E402
    CHAT_REASONING_TOKEN_BUDGETS,
    PROVIDER_MODEL_PRESETS,
    REVIEW_REASONING_EFFORTS,
    AIClientConfig,
)
from ai_pr_review.services import ai_client as ai_client_module  # noqa: E402
from ai_pr_review.services.ai_client import AIClient  # noqa: E402
from ai_pr_review.services.context_builder import ContextBuilder, FileContext  # noqa: E402
from ai_pr_review.services.exceptions import AIAuthenticationError  # noqa: E402
from ai_pr_review.services.model_capabilities import (  # noqa: E402
    calculate_review_output_budget,
    get_model_capabilities,
)
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


# ---------------------------------------------------------------------------
# 场景 B 的"长 diff"：合成一个接近真实 PR 规模的变更文件（200-400 行 patch）
# ---------------------------------------------------------------------------
#
# 合成而非抄一个真实 PR：脚本要能离线复跑，patch 行数（= prompt 规模）必须可复现，
# 也不该把某个真实仓库的代码带进来。改动前后两版都写成完整源码，patch 由
# `difflib.unified_diff` 逐行生成（n=3 上下文，与 GitHub 一致），再交给产品自己的
# `ContextBuilder`（tree-sitter 提 imports/functions/classes + 逐行窗口上下文）与
# `PromptAssembler` —— 与 `review_orchestrator._build_file_prompt` 同一条链路，
# 区别只在"文件从哪来"。改动里混了几处真实缺陷（拼串 SQL / 无超时 / 无重试 /
# 全局缓存），好让 max 档有实质内容可答（否则"答案是否被思考挤空"测不出来）。
LONG_DIFF_FILE = "demo/github_sync_pipeline.py"

_LONG_HANDLERS: tuple[tuple[str, str, str, str], ...] = (
    ("issues", "issue", "issues", "number"),
    ("pull_requests", "pull request", "pulls", "number"),
    ("labels", "label", "labels", "name"),
    ("milestones", "milestone", "milestones", "title"),
    ("comments", "comment", "issues/comments", "id"),
    ("reviews", "review", "pulls/comments", "id"),
    ("check_runs", "check run", "commits/check-runs", "id"),
    ("releases", "release", "releases", "tag_name"),
)

_LONG_HEADER: tuple[str, ...] = (
    '"""GitHub 数据同步管线（探针合成文件，非真实仓库代码）。"""',
    "",
    "from __future__ import annotations",
    "",
    "import logging",
    "import sqlite3",
    "import time",
    "",
    "import requests",
    "",
    "log = logging.getLogger(__name__)",
    "",
    'API_ROOT = "https://api.github.com"',
    "PAGE_SIZE = 100",
    "MAX_RETRIES = 4",
    "RETRY_BACKOFF = 1.5",
    "",
    "",
)


def _long_handler(
    index: int, name: str, noun: str, path: str, key_field: str, modern: bool
) -> list[str]:
    """一个同步函数的两版写法：`modern=False` 是改动前，`True` 是改动后（被审的那版）。"""
    table = f"sync_{name}"
    url_line = f'    url = f"{{API_ROOT}}/repos/{{owner}}/{{repo}}/{path}"'
    if modern:
        return [
            f"def sync_{name}(client, conn, owner, repo, cursor=None):",
            f'    """同步 {noun} 列表到本地表。"""',
            url_line,
            '    params = {"state": "all", "per_page": PAGE_SIZE}',
            "    if cursor:",
            '        params["since"] = cursor',
            "    payload = _get(client, url, params)",
            "    if payload is None:",
            f'        log.warning("{name}: 上游没有返回数据")',
            "        return 0",
            "    written = 0",
            "    for item in payload:",
            f'        key = item.get("{key_field}")',
            "        if key is None:",
            "            continue",
            "        if index % 2 == 0:",
            "            conn.execute(",
            f"                \"INSERT INTO {table} (key, title, body) VALUES ('%s', '%s', '%s')\"",
            '                % (key, item.get("title") or "", item.get("body") or "")',
            "            )",
            "        else:",
            "            conn.execute(",
            f'                "INSERT INTO {table} (key, title) VALUES (?, ?)"',
            '                " ON CONFLICT(key) DO UPDATE SET title = excluded.title",',
            '                (key, item.get("title") or ""),',
            "            )",
            f'        _SEEN[f"{name}:{{key}}"] = int(time.time())',
            "        written += 1",
            "    conn.commit()",
            f'    log.info("{name}: %s 行已写入", written)',
            "    return written",
            "",
        ]
    return [
        f"def sync_{name}(owner, repo, cursor=None):",
        f'    """同步 {noun} 列表到本地表。"""',
        url_line,
        '    params = {"state": "all", "per_page": PAGE_SIZE}',
        "    if cursor:",
        '        params["since"] = cursor',
        "    payload = requests.get(url, params=params).json()",
        "    written = 0",
        "    for item in payload:",
        f'        key = item.get("{key_field}")',
        "        if key is None:",
        "            continue",
        "        conn.execute(",
        f'            "INSERT INTO {table} (key, title) VALUES (?, ?)",',
        '            (key, item.get("title") or ""),',
        "        )",
        "        written += 1",
        "    conn.commit()",
        "    return written",
        "",
    ]


def _long_tail(modern: bool) -> list[str]:
    """文件尾部的请求助手与驱动函数（两版差异：重试 / 超时 / 连接复用）。"""
    sync_names = ", ".join(f"sync_{name}" for name, *_ in _LONG_HANDLERS)
    if modern:
        return [
            "def _get(client, url, params):",
            '    """带重试的 GET。"""',
            "    for attempt in range(MAX_RETRIES):",
            "        try:",
            "            response = client.get(url, params=params, timeout=30)",
            "            response.raise_for_status()",
            "            return response.json()",
            "        except requests.RequestException as exc:",
            "            if attempt == MAX_RETRIES - 1:",
            '                log.error("请求失败：%s", exc)',
            "                return None",
            "            time.sleep(RETRY_BACKOFF**attempt)",
            "    return None",
            "",
            "",
            "def _connect(db_path):",
            "    conn = sqlite3.connect(db_path)",
            '    conn.execute("PRAGMA journal_mode=WAL")',
            "    return conn",
            "",
            "",
            "def run_sync(owner, repo, db_path):",
            '    """同步一个仓库的全部实体。"""',
            "    client = requests.Session()",
            "    conn = _connect(db_path)",
            "    total = 0",
            "    for sync in (",
            f"        {sync_names},",
            "    ):",
            "        total += sync(client, conn, owner, repo)",
            "    conn.close()",
            "    return total",
        ]
    return [
        "def _get(url, params):",
        '    """GET（改动前：无重试、无超时）。"""',
        "    return requests.get(url, params=params).json()",
        "",
        "",
        "def run_sync(owner, repo, db_path):",
        '    """同步一个仓库的全部实体。"""',
        "    conn = sqlite3.connect(db_path)",
        "    total = 0",
        "    for sync in (",
        f"        {sync_names},",
        "    ):",
        "        total += sync(owner, repo)",
        "    conn.close()",
        "    return total",
    ]


def build_long_file(modern: bool) -> str:
    """改动前 / 改动后的完整文件源码（同一生成器的两个分支，保证 diff 可复现）。"""
    lines = list(_LONG_HEADER)
    if modern:
        # 全局可变缓存：真实 PR 里常见，也是被审代码里的一处并发隐患。
        lines += ["_SEEN: dict[str, int] = {}", "", ""]
    for index, (name, noun, path, key_field) in enumerate(_LONG_HANDLERS):
        lines += _long_handler(index, name, noun, path, key_field, modern)
    lines += _long_tail(modern)
    return "\n".join(lines).rstrip("\n") + "\n"


def build_long_patch() -> tuple[str, str]:
    """返回 (patch, 改动后的完整文件内容)——与 `FileDiff.patch` / `fetch_file_content` 同形。"""
    before = build_long_file(modern=False)
    after = build_long_file(modern=True)
    patch = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{LONG_DIFF_FILE}",
            tofile=f"b/{LONG_DIFF_FILE}",
            n=3,
        )
    )
    return patch, after


def log(message: str) -> None:
    print(message, flush=True)


@dataclass
class Scenario:
    """一个 review 调用场景（含它实际发出去的请求与拿回来的答案）。"""

    name: str
    # 旧口径（`--scenario legacy`）的夹具：直接写进请求体的 extra_params。
    # 新口径（`levels` / `long`）为空 dict，档位走产品入口 `level`。
    extra_params: dict[str, Any] = field(default_factory=dict)
    # 场景元信息（新口径用；legacy 留空）
    level: str = ""
    prompt_kind: str = "short"
    prompt_chars: int = 0
    diff_lines: int = 0
    # 实测
    ok: bool = False
    error: str | None = None
    duration_seconds: float = 0.0
    request_keys: dict[str, Any] = field(default_factory=dict)
    # 真实请求体里与思考有关的键（provider 追加的 policy 参数只能在这一层看到）
    wire_keys: dict[str, Any] = field(default_factory=dict)
    reasoning_chars: int = 0
    # `answer_chars` 是**产品拿去解析**的文本长度（`ProviderResponse.text`）；
    # `content_chars` 是原始 `message.content` 的长度。两者不等 = 走了
    # `_extract_message_text` 的 reasoning 兜底（`openai.py:463-473`）：
    # 那是"答案被思考挤空"的典型形态，JSON 必然解析失败（§6 #2）。
    answer_chars: int = 0
    content_chars: int = 0
    answer_from_reasoning: bool = False
    raw_json_parseable: bool = False
    findings_count: int = 0
    summary_chars: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    budget_headroom: int = 0
    finish_reason: str | None = None
    provider_calls: int = 0
    reasoning_on_response_field: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    def tokens_after_thinking(self) -> int:
        """扣掉 reasoning 之后剩给答案的 completion tokens（估）。

        `reasoning_tokens` 来自 DeepSeek 的 `usage.completion_tokens_details`；
        缺失时退回 0 = 全部算作答案（不猜）。
        """
        return max(0, self.completion_tokens - self.reasoning_tokens)


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


def build_long_prompts() -> tuple[str, str, dict[str, int]]:
    """场景 B 的 prompt：长 diff 走产品自己的 ContextBuilder + PromptAssembler。

    返回 (system, user, 规模统计)。规模统计进报告，避免"长"只是形容词。
    """
    patch, full_content = build_long_patch()
    file_context = ContextBuilder().build_context(LONG_DIFF_FILE, patch, full_content)
    assembler = PromptAssembler(response_language="zh-CN")
    system_prompt = assembler.build_system_prompt(file_context.language)
    user_prompt = assembler.build_user_prompt(file_context)
    stats = {
        "diff_lines": len(patch.splitlines()),
        "diff_chars": len(patch),
        "context_chars": len(file_context.diff_with_context),
        "system_chars": len(system_prompt),
        "user_chars": len(user_prompt),
        "prompt_chars": len(system_prompt) + len(user_prompt),
    }
    return system_prompt, user_prompt, stats


def build_client(
    key: str,
    model: str,
    base_url: str,
    extra_params: dict[str, Any],
    *,
    level: str | None = None,
) -> AIClient:
    """产品配置的客户端。

    - `level=None`：不碰档位字段（默认 `off`）——旧夹具场景与"现状"对照都走这条；
    - `level="low|high|max|off|auto"`：写进 `AIClientConfig.review_reasoning_effort`
      （= `preferences.review_reasoning_effort` 的运行时副本），由产品的
      `_review_reasoning_plan` 决定注入什么——**这是第二步之后的真实入口**。
    """
    config = AIClientConfig(
        api_key=key,
        provider="deepseek",
        model=model,
        base_url=base_url,
        api_format="openai",
        extra_params=dict(extra_params),
        # max_tokens 保持产品默认 4096 → 触发 `calculate_review_output_budget`
        # （deepseek：小输入 6144 / 输入 ≥12k 字符 8192，`model_capabilities.py:77-88`）。
        max_retries=1,
        timeout_seconds=300,
    )
    if level is not None:
        config.review_reasoning_effort = level
    return AIClient(config=config)


# 探针记录（跨场景共享，`instrument` 负责按场景清空）。
CHAT_CAPTURE: list[dict[str, Any]] = []


def install_chat_probe() -> None:
    """在**工厂层**拦截 `provider.chat`，记录 kwargs 与原始响应。

    只在 `client._provider.chat` 上包一层是不够的：开启档位时
    `_review_request_provider` 会为本次请求**新建一个 provider 副本**（`thinking` 走
    extra_params 通道），副本上的 `chat` 不是被包过的那一个——第一版探针因此把
    reasoning / completion tokens 全记成 0（2026-09-26 实跑的教训，见报告 §10.6）。
    挂在工厂上则"凡是本进程建的 provider"都被记录，与请求走哪条通道无关。
    """
    original_factory = ai_client_module.create_model_provider

    def recording_factory(config: Any, **kwargs: Any) -> Any:
        provider = original_factory(config, **kwargs)
        original_chat = provider.chat

        async def recording_chat(messages: list[dict[str, Any]], **chat_kwargs: Any) -> Any:
            response = await original_chat(messages, **chat_kwargs)
            CHAT_CAPTURE.append({"kwargs": chat_kwargs, "response": response})
            return response

        provider.chat = recording_chat
        return provider

    ai_client_module.create_model_provider = recording_factory  # type: ignore[assignment]


def instrument(client: AIClient) -> list[dict[str, Any]]:
    """开始记录本场景的调用：清空共享记录并返回它（拦截本身在 `install_chat_probe`）。"""
    del client  # 只为保持调用点语义（每个场景一个客户端）
    CHAT_CAPTURE.clear()
    return CHAT_CAPTURE


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
                WIRE_CAPTURE.append({key: payload.get(key, "<absent>") for key in WIRE_FIELDS})
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


def _reasoning_tokens(response: Any) -> int:
    """`usage.completion_tokens_details.reasoning_tokens`（DeepSeek 的思考 token 数）。

    缺失时不猜：返回 0，报告里由 `completion_tokens` 全额体现（宁可少报思考占比）。
    """
    raw = getattr(response, "raw_response", None)
    if not isinstance(raw, dict):
        return 0
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        return 0
    details = usage.get("completion_tokens_details")
    if not isinstance(details, dict):
        return 0
    value = details.get("reasoning_tokens")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _looks_like_json_object(text: str) -> bool:
    """产品解析前的第一道关卡（`ai_client._extract_json_payload` + `json.loads`）。

    只是**探针**：用来区分"答案被截断成半截 JSON"（这里 False，产品侧报
    `AIResponseFormatError`）与"JSON 合法但结构不合 schema"（这里 True、产品侧仍失败）。
    """
    stripped = text.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or start > end:
        return False
    try:
        json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return False
    return True


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
    text = getattr(response, "text", "") or ""
    content = message.get("content")
    scenario.content_chars = len(content) if isinstance(content, str) else 0
    scenario.answer_chars = len(text)
    scenario.answer_from_reasoning = scenario.content_chars == 0 and bool(text)
    scenario.raw_json_parseable = _looks_like_json_object(text)
    scenario.prompt_tokens = int(getattr(response, "input_tokens", 0) or 0)
    scenario.completion_tokens = int(getattr(response, "output_tokens", 0) or 0)
    scenario.reasoning_tokens = _reasoning_tokens(response)
    scenario.total_tokens = scenario.prompt_tokens + scenario.completion_tokens
    max_tokens = kwargs.get("max_tokens")
    if isinstance(max_tokens, int):
        scenario.budget_headroom = max_tokens - scenario.completion_tokens
    scenario.finish_reason = _finish_reason(response)
    scenario.reasoning_on_response_field = bool(getattr(response, "reasoning", None))


async def run_scenario(
    scenario: Scenario,
    key: str,
    model: str,
    base_url: str,
    system_prompt: str,
    user_prompt: str,
) -> Scenario:
    """跑一次真实 `review_code`。

    新口径（`scenario.level` 非空）走产品入口；旧口径（`scenario.extra_params`）走夹具。
    两条路的客户端构造只差一个字段，其余（`max_retries=1` / `timeout_seconds=300`）相同。
    """
    client = build_client(
        key,
        model,
        base_url,
        scenario.extra_params,
        level=scenario.level or None,
    )
    capture = instrument(client)
    scenario.prompt_chars = len(system_prompt) + len(user_prompt)
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


def run_planned(
    planned: list[Scenario],
    key: str,
    model: str,
    base_url: str,
    prompts: dict[str, tuple[str, str]],
) -> dict[str, Scenario]:
    """顺序跑完计划里的场景（每场景恰好 1 次调用），返回 name → Scenario。"""
    if not planned:
        return {}
    results: dict[str, Scenario] = {}
    for index, scenario in enumerate(planned, start=1):
        system_prompt, user_prompt = prompts[scenario.prompt_kind]
        log(
            f"[{index}/{len(planned)}] {scenario.name}: level={scenario.level or '-'} "
            f"extra_params={scenario.extra_params or '{}'} prompt={scenario.prompt_kind}"
            f"（{len(system_prompt) + len(user_prompt)} 字符"
            + (f"，diff {scenario.diff_lines} 行" if scenario.diff_lines else "")
            + "）..."
        )
        done = asyncio.run(run_scenario(scenario, key, model, base_url, system_prompt, user_prompt))
        results[scenario.name] = done
        log(
            f"    thinking={_wire_thinking(done)} effort={done.wire_keys.get('reasoning_effort', '-')} "
            f"max_tokens={done.wire_keys.get('max_tokens', '-')} · "
            f"reasoning={done.reasoning_chars} 字符/{done.reasoning_tokens} tok · "
            f"答案={done.answer_chars} 字符（content {done.content_chars}）· "
            f"completion={done.completion_tokens} tok · findings={done.findings_count} · "
            f"finish={done.finish_reason} · {done.duration_seconds:.1f}s"
            + (f" · error={done.error}" if done.error else "")
        )
        if done.error and ("401" in done.error or "认证" in done.error):
            raise _AuthAbort(done.error)
    return results


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


# ---------------------------------------------------------------------------
# 第二步口径：场景 A（四档 · 产品入口）/ 场景 B（长 diff × 高档位的预算边界）
# ---------------------------------------------------------------------------

# 任务约束：真实调用总次数 ≤8。计划超了就拒绝跑，不让参数组合悄悄多花钱。
CALL_BUDGET = 8


class _AuthAbort(RuntimeError):
    """密钥 / 认证不可用：立刻终止（这不是"档位结论"）。"""


def _gating_ok(checks: list[dict[str, Any]]) -> bool:
    return all(check["passed"] for check in checks if check["gating"])


def _wire_thinking(item: Scenario) -> str:
    value = item.wire_keys.get("thinking", "<absent>")
    if value in ({"type": "disabled"}, {"type": "enabled"}):
        return str(value["type"])
    return str(value)


def _cap_for(provider: str, model: str) -> tuple[int, str]:
    """档位预留的封顶值与来源（只读核对 `ai_client._review_max_output`：预设优先）。

    脚本不改产品代码：这里只把"产品会用哪个数字封顶"算出来，供报告解释实测值；
    证据始终是 wire 上真实的 `max_tokens`。
    """
    preset = PROVIDER_MODEL_PRESETS.get(provider.strip().lower(), {}).get(model)
    if preset is not None:
        return int(preset["max_output"]), "内置预设"
    return get_model_capabilities(provider, model).max_output_tokens, "能力档案"


def _expected_max_tokens(model: str, level: str, prompt_chars: int, cap: int) -> int:
    """该档位"应该"发出的 `max_tokens`（产品口径：基础额度 + 档位预留，受 cap 封顶）。"""
    base = calculate_review_output_budget("deepseek", model, input_chars=prompt_chars)
    if level in {"off", "auto"}:
        return base
    return max(1, min(base + CHAT_REASONING_TOKEN_BUDGETS.get(level, 0), cap))


def _calls_check(scenarios: list[Scenario], tag: str) -> dict[str, Any]:
    total = sum(item.provider_calls for item in scenarios)
    return _check(
        f"{tag}. 调用预算：每个场景恰好 1 次 provider 调用（无隐藏重试）",
        total == len(scenarios) and all(item.provider_calls == 1 for item in scenarios),
        True,
        f"total_provider_calls={total}, per_scenario="
        f"{ {item.name: item.provider_calls for item in scenarios} }",
    )


def evaluate_levels(
    scenarios: dict[str, Scenario],
    model: str,
    prompt_chars: int,
    cap: int,
    cap_source: str,
) -> list[dict[str, Any]]:
    """场景 A：产品入口（`AIClientConfig.review_reasoning_effort`）的四档。"""
    by_level = {name.removeprefix("level_"): item for name, item in scenarios.items()}
    prompt_kind_label = (
        "长 diff" if next(iter(scenarios.values())).prompt_kind == "long" else "短 diff"
    )
    checks: list[dict[str, Any]] = []

    wire_ok = True
    wire_detail: list[str] = []
    for level, item in by_level.items():
        expected_thinking = (
            {"type": "disabled"} if level in {"off", "auto"} else {"type": "enabled"}
        )
        expected_effort = "<absent>" if level in {"off", "auto"} else level
        expected_max = _expected_max_tokens(model, level, prompt_chars, cap)
        got_thinking = item.wire_keys.get("thinking", "<absent>")
        got_effort = item.wire_keys.get("reasoning_effort", "<absent>")
        got_max = item.wire_keys.get("max_tokens")
        ok = (
            got_thinking == expected_thinking
            and got_effort == expected_effort
            and got_max == expected_max
        )
        wire_ok = wire_ok and ok
        wire_detail.append(
            f"{level}: thinking={_wire_thinking(item)} effort={got_effort} "
            f"max_tokens={got_max}（期望 {expected_max}）{'✓' if ok else '✗'}"
        )
    checks.append(
        _check(
            "a1. 产品入口按规格表注入：off→policy 的 disabled；low/high/max→thinking=enabled + effort + 档位预算预留",
            wire_ok and bool(by_level),
            True,
            f"base({prompt_kind_label} {prompt_chars} 字符)；封顶={cap}（{cap_source}）；"
            + "；".join(wire_detail),
        )
    )

    off = by_level.get("off")
    if off is not None:
        checks.append(
            _check(
                "a2. off 档 = 现状：reasoning 0 字符、答案 JSON 可解析（内容非空）",
                off.ok and off.reasoning_chars == 0 and off.content_chars > 0,
                True,
                f"reasoning={off.reasoning_chars} 字符, content={off.content_chars} 字符, "
                f"summary={off.summary_chars}, findings={off.findings_count}, "
                f"finish={off.finish_reason}, error={off.error}",
            )
        )

    thinking_levels = [lv for lv in ("low", "high", "max") if lv in by_level]
    checks.append(
        _check(
            "a3. low/high/max 档 reasoning 均 > 0（档位真的开了思考）",
            bool(thinking_levels)
            and all(by_level[lv].ok and by_level[lv].reasoning_chars > 0 for lv in thinking_levels),
            True,
            "；".join(
                f"{lv}: reasoning={by_level[lv].reasoning_chars} 字符/"
                f"{by_level[lv].reasoning_tokens} tok, ok={by_level[lv].ok}, "
                f"error={by_level[lv].error}"
                for lv in thinking_levels
            ),
        )
    )

    if len(thinking_levels) == 3:
        low, high, maxi = (by_level[lv] for lv in thinking_levels)
        checks.append(
            _check(
                "a4. 单调 low < high < max（reasoning 字符；单次抽样，波动如实记录）",
                low.reasoning_chars < high.reasoning_chars < maxi.reasoning_chars,
                True,
                f"reasoning 字符 low={low.reasoning_chars} < high={high.reasoning_chars} "
                f"< max={maxi.reasoning_chars}（tokens: "
                f"{low.reasoning_tokens}/{high.reasoning_tokens}/{maxi.reasoning_tokens}）；"
                f"completion tokens: {low.completion_tokens}/{high.completion_tokens}/"
                f"{maxi.completion_tokens}；耗时 s: {low.duration_seconds:.1f}/"
                f"{high.duration_seconds:.1f}/{maxi.duration_seconds:.1f}",
            )
        )

    checks.append(_calls_check(list(scenarios.values()), "a5"))
    return checks


def evaluate_long(
    control: Scenario | None,
    runs: list[Scenario],
    model: str,
    prompt_chars: int,
    cap: int,
    cap_source: str,
) -> list[dict[str, Any]]:
    """场景 B：长 diff × 高档位——思考是否吃满额度、预留是否够、答案会不会被挤空。"""
    checks: list[dict[str, Any]] = []
    level = runs[0].level
    diff_lines = runs[0].diff_lines

    checks.append(
        _check(
            "b1. '长'是真的长：diff 在 200-400 行，prompt ≥12k 字符（触发产品 8192 基础额度）",
            200 <= diff_lines <= 400 and prompt_chars >= 12_000,
            True,
            f"diff={diff_lines} 行, prompt={prompt_chars} 字符, "
            f"基础额度={calculate_review_output_budget('deepseek', model, input_chars=prompt_chars)}",
        )
    )

    base = calculate_review_output_budget("deepseek", model, input_chars=prompt_chars)
    if control is not None:
        checks.append(
            _check(
                "b2. 长 diff × off 对照：answer JSON 可解析、reasoning=0、额度=基础额度（成本基线）",
                control.ok
                and control.reasoning_chars == 0
                and control.wire_keys.get("max_tokens") == base,
                True,
                f"max_tokens={control.wire_keys.get('max_tokens')}(期望 {base}), "
                f"reasoning={control.reasoning_chars} 字符, content={control.content_chars} 字符, "
                f"completion={control.completion_tokens} tok, {control.duration_seconds:.1f}s, "
                f"error={control.error}",
            )
        )

    checks.append(
        _check(
            f"b3. 长 diff × {level}：每次调用答案 JSON 都可解析（未被思考截断成半截 JSON / 空答案）",
            all(item.ok for item in runs),
            True,
            "；".join(
                f"#{index}: ok={item.ok}, raw_json={item.raw_json_parseable}, "
                f"content={item.content_chars} 字符, error={item.error}"
                for index, item in enumerate(runs, start=1)
            ),
        )
    )

    checks.append(
        _check(
            f"b4. 长 diff × {level}：finish_reason≠length 且额度有余量（没撞上限、没走 reasoning 兜底）",
            all(
                item.finish_reason != "length"
                and item.budget_headroom > 0
                and item.content_chars > 0
                and not item.answer_from_reasoning
                for item in runs
            ),
            True,
            "；".join(
                f"#{index}: finish={item.finish_reason}, completion={item.completion_tokens}/"
                f"{item.wire_keys.get('max_tokens')} tok（余量 {item.budget_headroom}）, "
                f"reasoning={item.reasoning_tokens} tok, 答案≈{item.tokens_after_thinking()} tok, "
                f"{item.duration_seconds:.1f}s"
                for index, item in enumerate(runs, start=1)
            ),
        )
    )

    reserve = CHAT_REASONING_TOKEN_BUDGETS.get(level, 0)
    expected_reserve = max(0, _expected_max_tokens(model, level, prompt_chars, cap) - base)
    checks.append(
        _check(
            f"b5. 预算预留实测 = +{expected_reserve} tok（档位请求 +{reserve}，受 max_output={cap} 封顶）",
            all(
                isinstance(item.wire_keys.get("max_tokens"), int)
                and int(item.wire_keys["max_tokens"]) - base == expected_reserve
                for item in runs
            ),
            True,
            f"封顶来源={cap_source}({cap}), 基础额度={base}, 期望预留=min({reserve}, {cap}-{base})"
            f"={expected_reserve}；实测 "
            + "；".join(
                f"#{index}: max_tokens={item.wire_keys.get('max_tokens')}"
                for index, item in enumerate(runs, start=1)
            ),
        )
    )

    checks.append(
        _check(
            f"b6. 长 diff × {level}：思考真实发生（reasoning_tokens>0）且思考之外仍有答案 token",
            all(item.reasoning_tokens > 0 and item.tokens_after_thinking() > 0 for item in runs),
            True,
            "；".join(
                f"#{index}: reasoning={item.reasoning_tokens} tok "
                f"(占请求额度 {100 * item.reasoning_tokens / max(1, int(item.wire_keys.get('max_tokens') or 1)):.1f}%), "
                f"答案≈{item.tokens_after_thinking()} tok"
                for index, item in enumerate(runs, start=1)
            ),
        )
    )

    checks.append(_calls_check(runs + ([control] if control is not None else []), "b7"))
    return checks


def render_live(summary: dict[str, Any]) -> None:
    log("")
    log("=" * 100)
    log(f"review 链路思考档位真机复验（产品入口 · 第二步后） · DeepSeek · {summary['model']}")
    log("=" * 100)
    scenarios = summary["scenarios"]
    # 表格按**角色**分组，不按 prompt 种类：`--scenario levels --prompt long` 时四档直接
    # 跑在长 diff 上，max 档同时是边界样本，两张表都要出现它。
    level_rows = [item for item in scenarios if item["name"].startswith("level_")]
    long_rows = [item for item in scenarios if item["name"].startswith("long_")]
    if not long_rows:
        long_rows = [
            item for item in level_rows if item["level"] == "max" and item["prompt_kind"] == "long"
        ]

    if level_rows:
        log("")
        prompt_note = (
            f"长 diff prompt {summary['prompt_stats'].get('prompt_chars', 0)} 字符"
            if level_rows[0]["prompt_kind"] == "long"
            else f"短 diff prompt {summary['prompt_stats'].get('short_prompt_chars', 0)} 字符"
        )
        log(f"场景 A · 四档（{prompt_note}）")
        log(
            f"{'档位':<8}{'thinking':<10}{'effort':<8}{'max_tok':>9}{'reason字符':>11}"
            f"{'reason tok':>11}{'compl tok':>10}{'答案tok':>9}{'答案字符':>10}"
            f"{'findings':>9}{'JSON':>6}{'finish':>8}{'耗时s':>8}"
        )
        for item in level_rows:
            log(
                f"{item['level'] or item['name']:<8}{_wire_row(item):<10}"
                f"{str(item['wire_keys'].get('reasoning_effort', '-')):<8}"
                f"{str(item['wire_keys'].get('max_tokens', '-')):>9}"
                f"{item['reasoning_chars']:>11}{item['reasoning_tokens']:>11}"
                f"{item['completion_tokens']:>10}{max(0, item['completion_tokens'] - item['reasoning_tokens']):>9}"
                f"{item['content_chars']:>10}{item['findings_count']:>9}"
                f"{('OK' if item['ok'] else 'FAIL'):>6}{str(item['finish_reason']):>8}"
                f"{item['duration_seconds']:>8.1f}"
            )
            if item["error"]:
                log(f"{'':<8}error: {item['error']}")

    if long_rows:
        stats = summary["prompt_stats"]
        log("")
        log(
            f"场景 B · 长 diff × 高档位（patch {stats.get('diff_lines', 0)} 行 / "
            f"{stats.get('diff_chars', 0)} 字符，prompt {stats.get('prompt_chars', 0)} 字符，"
            f"context {stats.get('context_chars', 0)} 字符）"
        )
        log(
            f"{'场景':<16}{'档位':<6}{'max_tok':>9}{'reason字符':>11}{'reason tok':>11}"
            f"{'compl tok':>10}{'答案tok':>9}{'余量':>7}{'答案字符':>10}"
            f"{'findings':>9}{'JSON':>6}{'finish':>8}{'耗时s':>8}"
        )
        for item in long_rows:
            log(
                f"{item['name']:<16}{item['level']:<6}"
                f"{str(item['wire_keys'].get('max_tokens', '-')):>9}"
                f"{item['reasoning_chars']:>11}{item['reasoning_tokens']:>11}"
                f"{item['completion_tokens']:>10}{max(0, item['completion_tokens'] - item['reasoning_tokens']):>9}"
                f"{item['budget_headroom']:>7}{item['content_chars']:>10}"
                f"{item['findings_count']:>9}{('OK' if item['ok'] else 'FAIL'):>6}"
                f"{str(item['finish_reason']):>8}{item['duration_seconds']:>8.1f}"
            )
            if item["error"]:
                log(f"{'':<16}error: {item['error']}")

    log("")
    log(
        f"封顶来源：{summary['cap_source']} = {summary['cap_tokens']} tokens（`_review_max_output` 同口径）"
    )
    log(f"总耗时：{summary['elapsed_seconds']}s · 总调用：{summary['total_provider_calls']}")
    log(
        "ProviderResponse.reasoning 字段非空："
        f"{sum(1 for item in scenarios if item['reasoning_on_response_field'])}"
        f"/{len(scenarios)} 个场景（非流式路径不回填该字段，见 §6 #2）"
    )
    log("")
    log("断言：")
    for check in summary["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        gate = "门禁" if check["gating"] else "参考"
        log(f"  [{mark}][{gate}] {check['name']}")
        log(f"          {check['detail']}")
    passed = sum(1 for check in summary["checks"] if check["passed"])
    gating_failed = [c["name"] for c in summary["checks"] if c["gating"] and not c["passed"]]
    log("")
    log(f"结论：断言 {passed}/{len(summary['checks'])} 通过；门禁失败 {len(gating_failed)} 条")
    for name in gating_failed:
        log(f"  - {name}")


def _wire_row(item: dict[str, Any]) -> str:
    value = item["wire_keys"].get("thinking", "<absent>")
    if value in ({"type": "disabled"}, {"type": "enabled"}):
        return str(value["type"])
    return str(value)


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
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"DeepSeek 模型名（默认 {DEFAULT_MODEL}）"
    )
    parser.add_argument(
        "--base-url", default="", help="覆盖 base_url（默认取 DEEPSEEK_BASE_URL 或官方）"
    )
    parser.add_argument(
        "--scenario",
        choices=("all", "levels", "long", "legacy"),
        default="all",
        help="all=四档+长 diff（默认，7 次调用）；levels=只跑四档；long=只跑长 diff；legacy=第一版 extra_params 夹具",
    )
    parser.add_argument(
        "--level",
        default="",
        help=f"只跑指定档位，可逗号分隔（{'/'.join(REVIEW_REASONING_EFFORTS)}）；legacy 场景忽略",
    )
    parser.add_argument(
        "--prompt",
        choices=("short", "long"),
        default="short",
        help="四档（levels）用哪份 prompt：short=最小 diff（默认）；long=200-400 行 patch（此时 max 档同时充当长 diff 边界样本）",
    )
    parser.add_argument(
        "--long-samples", type=int, default=2, help="长 diff × 高档位的采样次数（默认 2）"
    )
    parser.add_argument(
        "--no-long-control", action="store_true", help="跳过长 diff × off 对照（省一次调用）"
    )
    parser.add_argument("--json", action="store_true", help="只输出机器可读 JSON")
    args = parser.parse_args(argv)

    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        log("错误：DEEPSEEK_API_KEY 未设置（只从环境变量读取，不落盘）")
        return 2
    base_url = (
        args.base_url.strip() or os.environ.get("DEEPSEEK_BASE_URL", "").strip() or DEFAULT_BASE_URL
    )

    level_filter = [item.strip().lower() for item in args.level.split(",") if item.strip()]
    invalid_levels = [item for item in level_filter if item not in REVIEW_REASONING_EFFORTS]
    if invalid_levels:
        log(
            f"错误：--level 只接受 {'/'.join(REVIEW_REASONING_EFFORTS)}（可逗号分隔），"
            f"收到 {invalid_levels}"
        )
        return 2
    levels = tuple(
        lvl for lvl in ("off", "low", "high", "max") if not level_filter or lvl in level_filter
    )

    planned: list[Scenario] = []
    if args.scenario == "legacy":
        planned += [
            Scenario("default"),
            Scenario("effort_low_only", {"reasoning_effort": "low"}),
            Scenario("think_low", {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}),
            Scenario("think_max", {"thinking": {"type": "enabled"}, "reasoning_effort": "max"}),
        ]
    else:
        if args.scenario in {"all", "levels"}:
            planned += [
                Scenario(name=f"level_{lvl}", level=lvl, prompt_kind=args.prompt) for lvl in levels
            ]
        if args.scenario in {"all", "long"}:
            for lvl in level_filter or ["max"]:
                if lvl in {"off", "auto"}:
                    continue
                if not args.no_long_control:
                    planned.append(Scenario(name="long_off", level="off", prompt_kind="long"))
                planned += [
                    Scenario(name=f"long_{lvl}_{index}", level=lvl, prompt_kind="long")
                    for index in range(1, max(1, args.long_samples) + 1)
                ]

    if len(planned) > CALL_BUDGET:
        # 硬预算：探针不能因为参数组合悄悄多花调用。
        log(
            f"错误：本次计划 {len(planned)} 次真实调用，超过预算 {CALL_BUDGET} 次；请缩小 --long-samples"
        )
        return 2

    prompts: dict[str, tuple[str, str]] = {}
    prompt_stats: dict[str, int] = {}
    if any(item.prompt_kind == "short" for item in planned):
        prompts["short"] = build_prompts()
    if any(item.prompt_kind == "long" for item in planned):
        long_system, long_user, prompt_stats = build_long_prompts()
        prompts["long"] = (long_system, long_user)
    for item in planned:
        if item.prompt_kind == "long":
            item.diff_lines = int(prompt_stats.get("diff_lines", 0))

    install_wire_probe()
    install_chat_probe()
    started = time.monotonic()
    try:
        results = run_planned(planned, key, args.model, base_url, prompts)
    except _AuthAbort as exc:
        log(f"    key 无效或不可用（{exc}），终止")
        return 2
    if all(item.error for item in results.values()):
        # 全部场景失败 = 环境/模型名问题，不是"档位结论"，按退出码约定报 2。
        log(f"全部场景失败（首个错误：{next(iter(results.values())).error}）——按环境不可用处理")
        return 2

    if args.scenario == "legacy":
        checks = evaluate(results)
        summary: dict[str, Any] = {
            "provider": "deepseek",
            "model": args.model,
            "scenario": "legacy",
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
        return 0 if _gating_ok(checks) else 1

    cap, cap_source = _cap_for("deepseek", args.model)
    prompt_chars = {kind: len(system) + len(user) for kind, (system, user) in prompts.items()}
    checks = []
    level_results = {name: item for name, item in results.items() if name.startswith("level_")}
    if level_results:
        levels_kind = next(iter(level_results.values())).prompt_kind
        checks += evaluate_levels(
            level_results, args.model, prompt_chars[levels_kind], cap, cap_source
        )
    long_control = results.get("long_off")
    long_runs = [
        i for name, i in results.items() if name.startswith("long_") and i is not long_control
    ]
    if not long_runs:
        # 四档直接跑在长 diff 上（`--scenario levels --prompt long`）时，max 档本身就是
        # "长 diff × max"的边界样本：同一份数据再按边界口径过一遍断言。
        long_runs = [
            item
            for item in level_results.values()
            if item.level == "max" and item.prompt_kind == "long"
        ]
    if long_runs:
        checks += evaluate_long(
            long_control, long_runs, args.model, prompt_chars["long"], cap, cap_source
        )
    summary = {
        "provider": "deepseek",
        "model": args.model,
        "scenario": args.scenario,
        "cap_tokens": cap,
        "cap_source": cap_source,
        "prompt_stats": {k: v for k, v in prompt_stats.items()}
        | {"short_prompt_chars": prompt_chars.get("short", 0)},
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "total_provider_calls": sum(item.provider_calls for item in results.values()),
        "scenarios": [item.to_json() for item in results.values()],
        "checks": checks,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        render_live(summary)
    return 0 if _gating_ok(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
