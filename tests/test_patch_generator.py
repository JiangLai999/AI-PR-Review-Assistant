"""L3 修复建议 patch 测试（docs/repo-aware-review-plan.md §6）。

覆盖四层：

1. ``is_valid_unified_diff`` / ``extract_unified_diff``：合法 diff 通过，
   带解释文字 / 缺 ``@@`` / 空串 / 行数与 hunk 头不符 / 非 diff 行一律拒绝；
2. ``PatchGenerator``：stub 注入、异常降级为空串、重试上限、无模型调用面降级、
   token 用量累计；
3. 配置开关 ``preferences.suggested_patch``：默认关闭、归一化、落盘往返、
   旧配置静默加载；
4. 编排器集成：只对 critical/high 且 evidence_status=="valid" 的 finding 生成、
   开关关闭零构造零调用、metadata 统计正确、模型自述的 patch 被清空。

所有测试都不碰网络与凭据：模型调用一律走 stub。
"""

from __future__ import annotations

import asyncio
import json
import warnings
from typing import Any

import pytest

from ai_pr_review.config import (
    DEFAULT_SUGGESTED_PATCH,
    AIClientConfig,
    AppConfig,
    PRFetcherConfig,
    PreferencesConfig,
    ResultStoreConfig,
    normalize_suggested_patch,
)
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.context_builder import FileContext
from ai_pr_review.services.filter_pipeline import FilterPipelineResult
from ai_pr_review.services.patch_generator import (
    PATCH_ELIGIBLE_EVIDENCE_STATUS,
    PATCH_ELIGIBLE_SEVERITIES,
    PatchGenerator,
    build_patch_prompts,
    extract_unified_diff,
    is_patch_eligible,
    is_valid_unified_diff,
    validate_unified_diff,
)
from ai_pr_review.services.prompt_assembler import Finding, PromptAssembler, ReviewResult
from ai_pr_review.services.review_orchestrator import ReviewOrchestrator

# ---------------------------------------------------------------------------
# 1. diff 语法校验
# ---------------------------------------------------------------------------

SIMPLE_DIFF = "@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 2\n"
HEADERED_DIFF = (
    "diff --git a/src/a.py b/src/a.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/src/a.py\n"
    "+++ b/src/a.py\n"
    "@@ -1,3 +1,4 @@\n"
    " import os\n"
    "-x = 1\n"
    "+x = 2\n"
    "+y = 3\n"
    " print(x)\n"
)


@pytest.mark.parametrize(
    "text",
    [
        SIMPLE_DIFF,
        HEADERED_DIFF,
        # 省略行数的 hunk 头（-1 +1 等价于 -1,1 +1,1）
        "@@ -1 +1 @@\n-old\n+new\n",
        # 多段 hunk：每段各自计数
        "@@ -1,1 +1,1 @@\n-a\n+b\n@@ -10,1 +10,1 @@\n-c\n+d\n",
        # 尾部带函数名的 hunk 头
        "@@ -1,1 +1,1 @@ def f():\n-a\n+b\n",
        # "\ No newline at end of file" 不计入行数
        "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n",
        # 上下文行为空行（许多模型如此输出）
        "@@ -1,2 +1,2 @@\n\n-a\n+b\n",
        # 空白包裹
        "\n" + SIMPLE_DIFF + "\n",
    ],
)
def test_valid_unified_diffs_are_accepted(text: str):
    assert is_valid_unified_diff(text) is True
    assert extract_unified_diff(text)


def test_code_fence_around_the_whole_answer_is_stripped():
    """模型几乎总会加围栏：整段被围栏包住时剥掉再校验（围栏不是解释文字）。"""
    fenced = f"```diff\n{SIMPLE_DIFF}```"

    assert is_valid_unified_diff(fenced) is True
    assert extract_unified_diff(fenced) == SIMPLE_DIFF.strip()


@pytest.mark.parametrize(
    "text",
    [
        "",  # 空串
        "   \n\n",  # 只有空白
        "No fix is possible from the provided content.",  # 纯解释文字
        f"Here is the patch:\n{SIMPLE_DIFF}",  # 前缀解释文字
        f"{SIMPLE_DIFF}This change fixes the bug.\n",  # 后缀解释文字
        "@@ -1 +1 @@\n-a\n+b\nNow the second hunk:\n@@ -1,2 +1,2 @@\n-x\n+y\n",  # hunk 之间的解释文字
        "-old\n+new\n",  # 缺 @@
        "@@ -1,2 +1,2 @@\n def f():\n",  # 只有上下文，没有 +/- 变更行
        "@@ -1,5 +1,5 @@\n-a\n+b\n",  # 行数与 hunk 头声明不符（半截输出）
        "@@ -1 +1\n-a\n+b\n",  # hunk 头不合法（缺结尾 @@）
        "@@ -1,1 +1,1 @@\n?weird\n+b\n",  # hunk 内非法行
        '{"suggested_patch": "@@ -1 +1 @@\\n-a\\n+b\\n"}',  # JSON 包装
        f"```diff\n{SIMPLE_DIFF}\n```\ntrailing prose",  # 围栏之外还有散文
        # 只是"长得像头部"的散文：按前缀判断会漏，按形状判断才拒得掉
        f"@@ garbage @@\n{SIMPLE_DIFF}",
        f"index of the bug is 3\n{SIMPLE_DIFF}",
        "diff --git a/x b/x\nindex nope\n@@ -1,1 +1,1 @@\n-a\n+b\n",
        # 反斜杠行只有 `\ No newline at end of file` 一种
        "@@ -1,1 +1,1 @@\n-a\n+b\n\\ this is not a diff marker\n",
        # 垂直制表符等不该被当成换行（splitlines 会，diff 解析器不会）
        "@@ -1,2 +1,2 @@\n def f():\x0b-a\n+b\n",
    ],
)
def test_invalid_outputs_are_rejected(text: str):
    assert is_valid_unified_diff(text) is False
    assert extract_unified_diff(text) == ""
    assert validate_unified_diff(text) is None


def test_non_string_input_is_rejected():
    for value in (None, 42, ["@@ -1 +1 @@"], {"diff": SIMPLE_DIFF}):
        assert is_valid_unified_diff(value) is False
        assert extract_unified_diff(value) == ""


def test_crlf_is_accepted_and_normalized_to_lf():
    """行分隔只认 CRLF/CR/LF，且落库的补丁统一成 LF（与 diff 工具的输出一致）。"""
    crlf = SIMPLE_DIFF.replace("\n", "\r\n")

    assert is_valid_unified_diff(crlf) is True
    assert extract_unified_diff(crlf) == SIMPLE_DIFF.strip()
    assert "\r" not in extract_unified_diff(crlf)


def test_a_deletion_line_starting_with_a_dash_is_not_a_file_header():
    """hunk 内的 ``--- x`` 是"删除了一行 `-- x`"，不是文件头，必须算作变更行。"""
    text = "@@ -1,2 +1,0 @@\n--- keep\n--- drop\n"

    assert is_valid_unified_diff(text) is True
    # 同一个"删除两行"的 hunk，若把头声明成 new=1（行数不符）即拒绝
    assert is_valid_unified_diff("@@ -1,2 +1,1 @@\n--- keep\n--- drop\n") is False


# ---------------------------------------------------------------------------
# 2. 达标判定 + PatchGenerator
# ---------------------------------------------------------------------------


def make_finding(
    *,
    severity: str = "critical",
    file: str = "src/a.py",
    line: int = 1,
    snippet: str = "new",
    title: str = "issue",
    evidence_status: str = "valid",
) -> Finding:
    return Finding(
        severity=severity,
        category="correctness",
        file=file,
        line_start=line,
        line_end=line,
        title=title,
        problem="problem",
        suggestion="suggestion",
        confidence=0.9,
        code_snippet=snippet,
        evidence_status=evidence_status,
    )


def make_context(
    file_path: str = "src/a.py",
    *,
    content: str = "new\nkeep\n",
    diff: str = "@@ -1 +1 @@\n-old\n+new",
) -> FileContext:
    return FileContext(
        file_path=file_path,
        language="python",
        diff=diff,
        diff_with_context=diff,
        imports=[],
        functions=[],
        classes=[],
        parse_mode="regex",
        full_content=content,
    )


class RecordingComplete:
    """可编程的 ``complete`` 替身：记录 prompt、按脚本返回或抛异常。"""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        response = self.responses.pop(0) if self.responses else ""
        if isinstance(response, Exception):
            raise response
        return response


class StubProviderResponse:
    def __init__(self, text: str, *, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class StubProvider:
    """provider 形态的替身：只有 ``chat``，与真实 provider 接口一致。"""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.chat_kwargs: list[dict[str, Any]] = []

    async def chat(self, messages, **kwargs):
        self.chat_kwargs.append({"messages": messages, **kwargs})
        response = self.responses.pop(0) if self.responses else ""
        if isinstance(response, Exception):
            raise response
        return response


class TestIsPatchEligible:
    @pytest.mark.parametrize("severity", sorted(PATCH_ELIGIBLE_SEVERITIES))
    def test_critical_and_high_with_valid_evidence_are_eligible(self, severity: str):
        assert PATCH_ELIGIBLE_EVIDENCE_STATUS == "valid"
        assert is_patch_eligible(make_finding(severity=severity)) is True

    @pytest.mark.parametrize(
        ("severity", "status"),
        [
            ("medium", "valid"),
            ("low", "valid"),
            ("info", "valid"),
            ("critical", "needs_review"),
            ("critical", "invalid"),
            ("critical", "unverified"),
            ("high", "needs_review"),
        ],
    )
    def test_other_combinations_are_not_eligible(self, severity: str, status: str):
        finding = make_finding(severity=severity, evidence_status=status)

        assert is_patch_eligible(finding) is False

    def test_case_and_whitespace_do_not_smuggle_a_finding_in(self):
        """判定前统一 trim/lower：自定义 finding 替身（字段没经 pydantic 归一化）
        写 ``"CRITICAL"`` / ``" Valid "`` 时也必须得出同一结论。"""

        class LooseFinding:
            severity = " CRITICAL "
            evidence_status = "Valid"

        assert is_patch_eligible(LooseFinding()) is True


class TestPatchGeneratorDegradation:
    async def test_a_valid_diff_is_returned_and_counted(self):
        complete = RecordingComplete([SIMPLE_DIFF])
        generator = PatchGenerator(complete=complete)

        patch = await generator.generate(make_finding(), make_context())

        assert patch == SIMPLE_DIFF.strip()
        assert generator.calls == 1
        assert generator.usage_stats()["invalid_outputs"] == 0
        # prompt 带上了 finding 的事实与该文件内容
        _, user_prompt = complete.calls[0]
        assert "src/a.py" in user_prompt
        assert "suggestion" in user_prompt
        assert "new\nkeep" in user_prompt

    async def test_explanatory_text_degrades_to_empty(self):
        generator = PatchGenerator(complete=RecordingComplete([f"Sure!\n{SIMPLE_DIFF}"]))

        assert await generator.generate(make_finding(), make_context()) == ""
        assert generator.usage_stats()["invalid_outputs"] == 1

    async def test_call_exception_degrades_to_empty_without_raising(self):
        generator = PatchGenerator(complete=RecordingComplete([RuntimeError("boom")]))

        assert await generator.generate(make_finding(), make_context()) == ""
        assert generator.calls == 1

    async def test_retry_is_bounded_by_max_attempts(self):
        complete = RecordingComplete(["not a diff", SIMPLE_DIFF])
        generator = PatchGenerator(complete=complete, max_attempts=3)

        assert await generator.generate(make_finding(), make_context()) == SIMPLE_DIFF.strip()
        assert generator.calls == 2
        assert generator.usage_stats()["invalid_outputs"] == 1

        # 默认 max_attempts=1：只花一次调用，不重试
        single = PatchGenerator(complete=RecordingComplete(["not a diff", SIMPLE_DIFF]))
        assert single.max_attempts == 1
        assert await single.generate(make_finding(), make_context()) == ""
        assert single.calls == 1

    async def test_a_failing_prompt_build_still_degrades_to_empty(self):
        class ExplodingFinding:
            @property
            def file(self):
                raise RuntimeError("unexpected finding object")

        generator = PatchGenerator(complete=RecordingComplete([SIMPLE_DIFF]))

        assert await generator.generate(ExplodingFinding(), make_context()) == ""

    async def test_no_model_surface_means_no_call_and_empty_patch(self):
        class NoChatClient:
            pass

        generator = PatchGenerator(client=NoChatClient())

        assert await generator.generate(make_finding(), make_context()) == ""
        assert generator.calls == 0
        assert generator.usage_stats() == {
            "calls": 0,
            "invalid_outputs": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    async def test_a_broken_max_attempts_argument_does_not_raise(self):
        """构造参数写坏（inf / 负数 / 字符串）只降级，不抛——构造本身不该炸。"""
        for raw in (float("inf"), float("nan"), -3, "3", None):
            generator = PatchGenerator(
                complete=RecordingComplete([SIMPLE_DIFF]), max_attempts=raw
            )
            assert generator.max_attempts >= 1
            assert await generator.generate(make_finding(), make_context()) == SIMPLE_DIFF.strip()

    async def test_a_provider_is_called_with_the_patch_prompt(self):
        provider = StubProvider(
            [StubProviderResponse(SIMPLE_DIFF, input_tokens=120, output_tokens=30)]
        )
        generator = PatchGenerator(client=provider)

        patch = await generator.generate(make_finding(), make_context())

        assert patch == SIMPLE_DIFF.strip()
        kwargs = provider.chat_kwargs[0]
        assert kwargs["structured_output"] is False
        assert kwargs["messages"][0]["role"] == "user"
        # 系统提示只说规则，finding 与文件内容都在 user prompt 里（可注入的不可信数据）
        assert "src/a.py" not in kwargs["system_prompt"]
        assert "src/a.py" in kwargs["messages"][0]["content"]
        assert generator.usage_stats()["input_tokens"] == 120
        assert generator.usage_stats()["output_tokens"] == 30

    async def test_an_ai_client_surface_is_resolved_through_its_provider(self):
        """AIClient 没有 chat：生成器取它的 ``_provider``（真编排器就是这样用的）。"""

        class AIClientLike:
            def __init__(self, provider):
                self._provider = provider

        provider = StubProvider([StubProviderResponse(SIMPLE_DIFF)])
        generator = PatchGenerator(client=AIClientLike(provider))

        assert await generator.generate(make_finding(), make_context()) == SIMPLE_DIFF.strip()

    async def test_a_client_without_token_usage_reports_zero(self):
        """provider 不报用量时如实记 0，不编造数字。"""
        provider = StubProvider([StubProviderResponse(SIMPLE_DIFF)])
        generator = PatchGenerator(client=provider)

        assert await generator.generate(make_finding(), make_context()) == SIMPLE_DIFF.strip()
        assert generator.usage_stats()["input_tokens"] == 0
        assert generator.usage_stats()["output_tokens"] == 0


class TestPatchPrompts:
    def test_prompts_carry_the_finding_and_the_file_content(self):
        system_prompt, user_prompt = build_patch_prompts(
            make_finding(title="SQL injection", file="src/db.py", line=12),
            make_context("src/db.py", content="cursor.execute(q)\n", diff="-q\n+q"),
        )

        assert "unified diff" in system_prompt
        assert "empty response is a valid" in system_prompt
        assert "src/db.py" in user_prompt
        assert "SQL injection" in user_prompt
        assert "Lines: 12-12" in user_prompt
        assert "cursor.execute(q)" in user_prompt

    def test_related_files_are_not_injected(self):
        """补丁只允许改 finding 指向的文件：相关文件不进 prompt。"""
        context = make_context()
        context.related_files = [
            {
                "path": "tests/test_a.py",
                "reason": "test",
                "content": "def test_x(): pass",
                "truncated": False,
                "from_cache": False,
            }
        ]

        _, user_prompt = build_patch_prompts(make_finding(), context)

        assert "tests/test_a.py" not in user_prompt

    def test_missing_context_still_builds_a_prompt(self):
        _, user_prompt = build_patch_prompts(make_finding(), None)

        assert "src/a.py" in user_prompt

    def test_long_content_is_truncated(self):
        _, user_prompt = build_patch_prompts(
            make_finding(),
            make_context(content="x" * 5000),
            max_context_chars=100,
            max_diff_chars=50,
        )

        assert "[truncated]" in user_prompt
        assert "x" * 200 not in user_prompt


# ---------------------------------------------------------------------------
# 3. 配置开关（沿用既有 normalize 惯例）
# ---------------------------------------------------------------------------


def _preference_warnings(recorded: list) -> list[str]:
    return [str(item.message) for item in recorded if "preferences." in str(item.message)]


def test_suggested_patch_defaults_to_off_everywhere():
    """默认关闭：旧配置零改动，且不会给用户带来额外模型调用。"""
    assert DEFAULT_SUGGESTED_PATCH is False
    assert PreferencesConfig().suggested_patch is False
    assert AppConfig.from_env().preferences.suggested_patch is False

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        PreferencesConfig()
    assert _preference_warnings(recorded) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        (" TRUE ", True),
        ("yes", True),
        ("on", True),
        ("1", True),
        ("false", False),
        ("No", False),
        ("off", False),
        ("0", False),
    ],
)
def test_suggested_patch_accepts_the_usual_spellings(raw: object, expected: bool):
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        assert normalize_suggested_patch(raw) is expected
        assert PreferencesConfig(suggested_patch=raw).suggested_patch is expected
    assert _preference_warnings(recorded) == []


@pytest.mark.parametrize("raw", ["maybe", "", None, 2, [], {}, "enabled?"])
def test_invalid_suggested_patch_falls_back_to_off_with_a_warning(raw: object):
    """非法值只回退 + 告警，绝不抛异常：配置坏了也要能进 `pr-review config` 去修。"""
    with pytest.warns(RuntimeWarning, match="suggested_patch"):
        assert normalize_suggested_patch(raw) is False
    with pytest.warns(RuntimeWarning, match="suggested_patch"):
        assert PreferencesConfig(suggested_patch=raw).suggested_patch is False


def test_suggested_patch_survives_a_save_load_roundtrip(tmp_path):
    config_path = tmp_path / "config.json"
    config = AppConfig.from_env()
    config.preferences.suggested_patch = True
    config.save(config_path)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["preferences"]["suggested_patch"] is True
    assert AppConfig.load(config_path).preferences.suggested_patch is True


def test_a_legacy_config_without_suggested_patch_loads_silently(tmp_path):
    config_path = tmp_path / "config.json"
    config = AppConfig.from_env()
    config.save(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["preferences"].pop("suggested_patch")
    config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        loaded = AppConfig.load(config_path)

    assert _preference_warnings(recorded) == []
    assert loaded.preferences.suggested_patch is False


# ---------------------------------------------------------------------------
# 4. Finding 字段与模型侧 schema
# ---------------------------------------------------------------------------


class TestFindingField:
    def test_defaults_to_empty_and_stays_optional(self):
        assert make_finding().suggested_patch == ""
        # 模型返回的 JSON 不带该字段也必须能校验通过（旧 run / 旧模型输出）
        payload = {
            "summary": "s",
            "findings": [
                {
                    "severity": "critical",
                    "category": "correctness",
                    "file": "src/a.py",
                    "line_start": 1,
                    "line_end": 1,
                    "title": "t",
                    "problem": "p",
                    "suggestion": "s",
                    "confidence": 0.9,
                    "code_snippet": "new",
                }
            ],
        }
        assert ReviewResult.model_validate(payload).findings[0].suggested_patch == ""

    def test_the_model_facing_schema_neither_exposes_nor_requires_it(self):
        """服务端字段：模型看不到它，自然也不在必填里（否则模型会自造补丁）。"""
        schema = PromptAssembler().get_json_schema()
        finding_schema = schema["$defs"]["Finding"]

        assert "suggested_patch" not in finding_schema["properties"]
        assert "suggested_patch" not in finding_schema["required"]
        assert "suggested_patch" not in json.dumps(schema)
        assembled = PromptAssembler().build_system_prompt("python")
        assert "suggested_patch" not in assembled
        # 服务端已有的字段仍在（没有误删）
        assert "evidence_status" not in finding_schema["properties"]
        assert "title" in finding_schema["properties"]

    def test_an_empty_patch_is_left_out_of_the_payload(self):
        """空值不落进 payload：加法式字段不得改变既有字节级快照。

        `pr-review demo --json-output` 的 SHA-256 冻结用例（`tests/test_cli.py:2487`）
        直接序列化 `Finding`；输出 `"suggested_patch": ""` 会让它红。省略即
        「本次没有补丁建议」，反序列化侧有默认值，新旧 payload 都能读。
        """
        empty = ReviewResult(summary="s", findings=[make_finding()])

        assert "suggested_patch" not in empty.model_dump()["findings"][0]
        assert "suggested_patch" not in json.loads(empty.model_dump_json())["findings"][0]
        assert "suggested_patch" not in json.dumps(empty.model_dump(mode="json"))

        patch = SIMPLE_DIFF.strip()
        patched = ReviewResult(
            summary="s",
            findings=[make_finding().model_copy(update={"suggested_patch": patch})],
        )
        assert patched.model_dump()["findings"][0]["suggested_patch"] == patch
        assert json.loads(patched.model_dump_json())["findings"][0]["suggested_patch"] == patch
        # 有值/无值两种 payload 都能读回同一个模型
        reloaded = ReviewResult.model_validate_json(patched.model_dump_json())
        assert reloaded.findings[0].suggested_patch == patch
        unpatched = ReviewResult.model_validate_json(empty.model_dump_json())
        assert unpatched.findings[0].suggested_patch == ""

    def test_round_trips_through_the_stored_payload(self):
        finding = make_finding().model_copy(update={"suggested_patch": SIMPLE_DIFF.strip()})

        restored = ReviewResult.model_validate_json(
            ReviewResult(summary="s", findings=[finding]).model_dump_json()
        )

        assert restored.findings[0].suggested_patch == SIMPLE_DIFF.strip()


# ---------------------------------------------------------------------------
# 5. 编排器集成（标准编排器：单 run 级 AIClient，见 docs/claude-l3-patch.md）
# ---------------------------------------------------------------------------

#: 与 test_review_orchestrator 同一套事实：第 1 行是 diff 的变更行，第 2 行不是，
#: 第 9 行不存在。据此让真实 FindingValidator 给出三种证据结论。
CONTEXT_FILE_CONTENT = "new\nkeep\n"
PR_URL = "https://github.com/owner/repo/pull/42"


def finding_payload(
    file: str,
    *,
    severity: str,
    line: int = 1,
    snippet: str = "new",
    title: str,
) -> Finding:
    return Finding(
        severity=severity,
        category="correctness",
        file=file,
        line_start=line,
        line_end=line,
        title=title,
        problem="problem",
        suggestion="suggestion",
        confidence=0.95,
        code_snippet=snippet,
        sources=["ai_analysis"],
    )


class StubPRFetcher:
    def __init__(self, *args, **kwargs):
        pass

    def fetch(self, pr_url: str) -> PRData:
        return PRData(
            pr_number=42,
            title="L3 patch",
            description="desc",
            author="alice",
            state="open",
            head_sha="head123",
            base_sha="base123",
            head_ref="feature",
            base_ref="main",
            diff="diff",
            files=[
                FileDiff(
                    filename="src/file_0.py",
                    status=FileStatus.MODIFIED,
                    additions=1,
                    deletions=0,
                    changes=1,
                    patch="@@ -1 +1 @@\n-old\n+new",
                )
            ],
            url=pr_url,
            merged=False,
            owner="owner",
            repo="repo",
        )

    def fetch_file_content(self, owner: str, repo: str, file_path: str, ref: str) -> str | None:
        return CONTEXT_FILE_CONTENT


class StubFilterPipeline:
    def __init__(self, *args, **kwargs):
        pass

    def filter_pr_data(self, pr_data: PRData):
        result = FilterPipelineResult()
        result.results = [
            type("FilterResult", (), {"file": file_diff, "included": True})()
            for file_diff in pr_data.files
        ]
        return pr_data, result


class StubContextBuilder:
    def __init__(self, *args, **kwargs):
        pass

    def build_context(self, file_path: str, diff: str, full_content: str) -> FileContext:
        return FileContext(
            file_path=file_path,
            language="python",
            diff=diff,
            diff_with_context=diff,
            imports=[],
            functions=[],
            classes=[],
            parse_mode="regex",
            full_content=full_content,
        )


class StubPromptAssembler:
    def __init__(self, *args, **kwargs):
        pass

    def build_system_prompt(self, language: str) -> str:
        return "system"

    def build_user_prompt(self, file_context: FileContext, review_plan: Any = None) -> str:
        return file_context.file_path


class StubPostProcessor:
    def __init__(self, *args, **kwargs):
        pass

    def process(self, result: ReviewResult) -> ReviewResult:
        return result

    def process_with_stats(self, result: ReviewResult) -> tuple[ReviewResult, dict[str, Any]]:
        return result, {}


class StubResultStore:
    last: StubResultStore | None = None

    def __init__(self, *args, **kwargs):
        StubResultStore.last = self
        self.saved: tuple[str, ReviewResult, dict[str, Any]] | None = None

    def save_result(self, pr_url: str, result: ReviewResult, **kwargs) -> str:
        self.saved = (pr_url, result, kwargs)
        return "run-l3"

    @property
    def saved_metadata(self) -> dict[str, Any]:
        assert self.saved is not None, "save_result 没有被调用"
        return self.saved[2].get("metadata") or {}


def scenario_ai_client(
    findings: list[Finding],
    *,
    patch_responses: list[Any] | None = None,
    chat_calls: list[dict[str, Any]] | None = None,
) -> type:
    """AIClient 替身：逐文件审查返回预置 finding；可选地实现 provider 形态的 chat。"""

    class ScenarioAIClient:
        instances: list[ScenarioAIClient] = []

        def __init__(self, *args, **kwargs):
            self.total_run_cost = 0.5
            self.config = kwargs.get("config")
            ScenarioAIClient.instances.append(self)

        async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
            return ReviewResult(summary=f"reviewed {user_prompt}", findings=list(findings))

        async def chat(self, messages, **kwargs):
            if chat_calls is not None:
                chat_calls.append({"messages": messages, **kwargs})
            response = patch_responses.pop(0) if patch_responses else ""
            if isinstance(response, Exception):
                raise response
            return StubProviderResponse(response, input_tokens=10, output_tokens=5)

    return ScenarioAIClient


class RecordingPatchGenerator:
    """记录构造与逐条生成的生成器替身（也用来证明"关闭时零构造"）。"""

    constructions = 0
    instances: list[RecordingPatchGenerator] = []
    #: 按 finding.title 预置返回值；未预置的一律返回 ""
    patches: dict[str, str] = {}
    error: Exception | None = None

    @classmethod
    def reset(cls, patches: dict[str, str] | None = None, error: Exception | None = None):
        cls.constructions = 0
        cls.instances = []
        cls.patches = dict(patches or {})
        cls.error = error

    def __init__(self, *args, **kwargs):
        RecordingPatchGenerator.constructions += 1
        RecordingPatchGenerator.instances.append(self)
        self.client = kwargs.get("client")
        self.seen: list[tuple[str, str]] = []

    async def generate(self, finding: Finding, file_context: FileContext) -> str:
        self.seen.append((finding.title, file_context.file_path))
        if RecordingPatchGenerator.error is not None:
            raise RecordingPatchGenerator.error
        return RecordingPatchGenerator.patches.get(finding.title, "")

    def usage_stats(self) -> dict[str, int]:
        return {
            "calls": len(self.seen),
            "invalid_outputs": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }


def _l3_config(tmp_path, *, suggested_patch: bool) -> AppConfig:
    config = AppConfig.from_env()
    config.pr_fetcher = PRFetcherConfig(github_token="token", fetch_concurrency=2)
    config.ai_client = AIClientConfig(api_key="api-key", review_concurrency=1)
    config.result_store = ResultStoreConfig(db_path=str(tmp_path / "results.db"))
    config.preferences.suggested_patch = suggested_patch
    return config


def _patch_orchestrator(monkeypatch, *, ai_client: type) -> None:
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", StubPRFetcher)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.FilterPipeline", StubFilterPipeline
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ContextBuilder", StubContextBuilder
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PromptAssembler", StubPromptAssembler
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.AIClient", ai_client)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PostProcessor", StubPostProcessor
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.ResultStore", StubResultStore)


class TestOrchestratorIntegration:
    def test_only_eligible_findings_get_a_patch(self, monkeypatch, tmp_path):
        """达标 = critical/high 且 valid；medium 与未通过证据校验的一律不生成。"""
        findings = [
            finding_payload("src/file_0.py", severity="critical", title="critical valid"),
            finding_payload("src/file_0.py", severity="high", title="high valid"),
            # 第 2 行不是变更行 → needs_review
            finding_payload(
                "src/file_0.py", severity="critical", line=2, snippet="keep", title="critical nr"
            ),
            # 第 9 行不存在 → invalid
            finding_payload(
                "src/file_0.py", severity="high", line=9, snippet="keep", title="high invalid"
            ),
            finding_payload("src/file_0.py", severity="medium", title="medium valid"),
            finding_payload("src/file_0.py", severity="low", title="low valid"),
        ]
        RecordingPatchGenerator.reset(patches={"critical valid": SIMPLE_DIFF})
        client_class = scenario_ai_client(findings)
        _patch_orchestrator(monkeypatch, ai_client=client_class)
        monkeypatch.setattr(
            "ai_pr_review.services.review_orchestrator.PatchGenerator", RecordingPatchGenerator
        )

        artifacts = asyncio.run(
            ReviewOrchestrator(_l3_config(tmp_path, suggested_patch=True)).review(PR_URL)
        )

        generator = RecordingPatchGenerator.instances[0]
        # 只对两条达标 finding 调用了生成器（按 finding.file 找到该文件的上下文）
        assert generator.seen == [
            ("critical valid", "src/file_0.py"),
            ("high valid", "src/file_0.py"),
        ]
        # 生成器拿到的是本 run 的 AIClient（同一条成本/预算链路）
        assert generator.client is client_class.instances[0]

        by_title = {finding.title: finding for finding in artifacts.review_result.findings}
        assert by_title["critical valid"].suggested_patch.strip() == SIMPLE_DIFF.strip()
        assert by_title["critical valid"].evidence_status == "valid"
        assert by_title["high valid"].suggested_patch == ""
        assert by_title["critical nr"].suggested_patch == ""
        assert by_title["high invalid"].suggested_patch == ""
        assert by_title["medium valid"].suggested_patch == ""
        assert by_title["low valid"].suggested_patch == ""

        stats = StubResultStore.last.saved_metadata["suggested_patches"]
        assert stats["enabled"] is True
        assert stats["candidates"] == 2
        assert stats["patches_generated"] == 1
        assert stats["patches_skipped"] == 1

    def test_the_switch_off_means_zero_constructions_and_zero_calls(self, monkeypatch, tmp_path):
        finding = finding_payload(
            "src/file_0.py", severity="critical", title="critical valid"
        ).model_copy(update={"suggested_patch": "@@ -1 +1 @@\n-a\n+b\n"})
        RecordingPatchGenerator.reset(patches={"critical valid": SIMPLE_DIFF})
        _patch_orchestrator(monkeypatch, ai_client=scenario_ai_client([finding]))
        monkeypatch.setattr(
            "ai_pr_review.services.review_orchestrator.PatchGenerator", RecordingPatchGenerator
        )

        artifacts = asyncio.run(
            ReviewOrchestrator(_l3_config(tmp_path, suggested_patch=False)).review(PR_URL)
        )

        assert RecordingPatchGenerator.constructions == 0
        # 开关关闭时连模型自述的补丁也一并清空：该字段只由 PatchGenerator 写入
        assert artifacts.review_result.findings[0].suggested_patch == ""
        assert StubResultStore.last.saved_metadata["suggested_patches"] == {
            "enabled": False,
            "candidates": 1,
            "patches_generated": 0,
            "patches_skipped": 0,
            "calls": 0,
            "patches_invalid": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    def test_generation_failure_is_skipped_and_never_breaks_the_run(self, monkeypatch, tmp_path):
        findings = [finding_payload("src/file_0.py", severity="critical", title="critical valid")]
        RecordingPatchGenerator.reset(error=RuntimeError("generator exploded"))
        _patch_orchestrator(monkeypatch, ai_client=scenario_ai_client(findings))
        monkeypatch.setattr(
            "ai_pr_review.services.review_orchestrator.PatchGenerator", RecordingPatchGenerator
        )

        artifacts = asyncio.run(
            ReviewOrchestrator(_l3_config(tmp_path, suggested_patch=True)).review(PR_URL)
        )

        assert artifacts.run_id == "run-l3"
        assert artifacts.review_result.findings[0].suggested_patch == ""
        stats = StubResultStore.last.saved_metadata["suggested_patches"]
        assert stats["patches_generated"] == 0
        assert stats["patches_skipped"] == 1

    def test_an_eligible_finding_without_file_context_is_skipped_not_generated(
        self, monkeypatch, tmp_path
    ):
        """达标但找不到该文件的上下文（模型点名了本次没审的文件）→ 跳过，不猜。"""
        RecordingPatchGenerator.reset()
        _patch_orchestrator(monkeypatch, ai_client=scenario_ai_client([]))
        monkeypatch.setattr(
            "ai_pr_review.services.review_orchestrator.PatchGenerator", RecordingPatchGenerator
        )
        orchestrator = ReviewOrchestrator(_l3_config(tmp_path, suggested_patch=True))
        finding = make_finding(file="src/not_reviewed.py")

        patched, stats = asyncio.run(
            orchestrator._attach_suggested_patches(
                ReviewResult(summary="s", findings=[finding]),
                [],
                scenario_ai_client([])(),
                None,
            )
        )

        assert patched.findings[0].suggested_patch == ""
        assert RecordingPatchGenerator.instances[0].seen == []
        assert stats["candidates"] == 1
        assert stats["patches_skipped"] == 1
        assert stats["calls"] == 0

    def test_a_generator_that_cannot_be_built_is_reported_as_skipped(self, monkeypatch, tmp_path):
        """生成器构造失败也不能让整轮审查失败：达标条数如实记为跳过。"""

        class ExplodingGenerator:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("no generator today")

        findings = [finding_payload("src/file_0.py", severity="critical", title="critical valid")]
        _patch_orchestrator(monkeypatch, ai_client=scenario_ai_client(findings))
        monkeypatch.setattr(
            "ai_pr_review.services.review_orchestrator.PatchGenerator", ExplodingGenerator
        )

        artifacts = asyncio.run(
            ReviewOrchestrator(_l3_config(tmp_path, suggested_patch=True)).review(PR_URL)
        )

        assert artifacts.run_id == "run-l3"
        assert artifacts.review_result.findings[0].suggested_patch == ""
        stats = StubResultStore.last.saved_metadata["suggested_patches"]
        assert stats["enabled"] is True
        assert stats["candidates"] == 1
        assert stats["patches_generated"] == 0
        assert stats["patches_skipped"] == 1
        assert stats["calls"] == 0

    def test_broken_usage_stats_do_not_break_the_run(self, monkeypatch, tmp_path):
        """统计读不出来时补丁照常写回，数字记 0（不编造、不抛）。"""

        class OddStatsGenerator(RecordingPatchGenerator):
            def usage_stats(self):
                raise RuntimeError("no stats")

        findings = [finding_payload("src/file_0.py", severity="critical", title="critical valid")]
        RecordingPatchGenerator.reset(patches={"critical valid": SIMPLE_DIFF})
        _patch_orchestrator(monkeypatch, ai_client=scenario_ai_client(findings))
        monkeypatch.setattr(
            "ai_pr_review.services.review_orchestrator.PatchGenerator", OddStatsGenerator
        )

        artifacts = asyncio.run(
            ReviewOrchestrator(_l3_config(tmp_path, suggested_patch=True)).review(PR_URL)
        )

        assert artifacts.review_result.findings[0].suggested_patch.strip() == SIMPLE_DIFF.strip()
        stats = StubResultStore.last.saved_metadata["suggested_patches"]
        assert stats["patches_generated"] == 1
        assert stats["calls"] == 0
        assert stats["input_tokens"] == 0

    def test_a_model_authored_patch_is_dropped(self, monkeypatch, tmp_path):
        """schema 里没有该字段，模型自述的补丁不得进入报告（服务端字段原则）。"""
        finding = finding_payload(
            "src/file_0.py", severity="critical", title="critical valid"
        ).model_copy(update={"suggested_patch": "@@ -1 +1 @@\n-a\n+b\n"})
        RecordingPatchGenerator.reset()
        _patch_orchestrator(monkeypatch, ai_client=scenario_ai_client([finding]))
        monkeypatch.setattr(
            "ai_pr_review.services.review_orchestrator.PatchGenerator", RecordingPatchGenerator
        )

        artifacts = asyncio.run(
            ReviewOrchestrator(_l3_config(tmp_path, suggested_patch=True)).review(PR_URL)
        )

        assert artifacts.review_result.findings[0].suggested_patch == ""

    def test_the_real_generator_is_wired_end_to_end_with_the_client(self, monkeypatch, tmp_path):
        """真实 PatchGenerator + provider 形态的 chat：合法 diff 落库，非法输出落空。"""
        chat_calls: list[dict[str, Any]] = []
        patch_responses: list[Any] = [
            f"Here you go:\n{SIMPLE_DIFF}",  # 带解释文字 → 拒绝
            SIMPLE_DIFF,  # 合法 → 采纳
        ]
        findings = [
            finding_payload("src/file_0.py", severity="critical", title="critical valid"),
            finding_payload("src/file_0.py", severity="high", title="high valid"),
            finding_payload("src/file_0.py", severity="medium", title="medium valid"),
        ]
        _patch_orchestrator(
            monkeypatch,
            ai_client=scenario_ai_client(
                findings, patch_responses=patch_responses, chat_calls=chat_calls
            ),
        )

        artifacts = asyncio.run(
            ReviewOrchestrator(_l3_config(tmp_path, suggested_patch=True)).review(PR_URL)
        )

        # 只有两条达标 finding 各发起一次补丁调用（medium 不生成）
        assert len(chat_calls) == 2
        assert all(call["structured_output"] is False for call in chat_calls)
        by_title = {finding.title: finding for finding in artifacts.review_result.findings}
        assert by_title["critical valid"].suggested_patch == ""
        assert by_title["high valid"].suggested_patch == SIMPLE_DIFF.strip()
        assert by_title["medium valid"].suggested_patch == ""

        stats = StubResultStore.last.saved_metadata["suggested_patches"]
        assert stats["calls"] == 2
        assert stats["patches_invalid"] == 1
        assert stats["patches_generated"] == 1
        assert stats["patches_skipped"] == 1
        assert stats["input_tokens"] == 20
        assert stats["output_tokens"] == 10

    def test_the_patch_reaches_the_persisted_review_result(self, monkeypatch, tmp_path):
        findings = [finding_payload("src/file_0.py", severity="critical", title="critical valid")]
        _patch_orchestrator(
            monkeypatch,
            ai_client=scenario_ai_client(findings, patch_responses=[SIMPLE_DIFF]),
        )

        asyncio.run(
            ReviewOrchestrator(_l3_config(tmp_path, suggested_patch=True)).review(PR_URL)
        )

        saved_result = StubResultStore.last.saved[1]
        assert saved_result.findings[0].suggested_patch == SIMPLE_DIFF.strip()
        # 报告 JSON payload 走 model_dump，字段自动带上（无需改渲染层）
        payload = json.loads(saved_result.model_dump_json())
        assert payload["findings"][0]["suggested_patch"] == SIMPLE_DIFF.strip()
