"""CLI entry module tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

import ai_pr_review.cli as cli_module
import ai_pr_review.config as config_module
import ai_pr_review.services.review_orchestrator as orchestrator_module
from ai_pr_review.cli import main
from ai_pr_review.config import (
    AIClientConfig,
    AppConfig,
    PostProcessorConfig,
    ProviderConfig,
    ReportRendererConfig,
    ResultStoreConfig,
)
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.context_builder import FileContext
from ai_pr_review.services.exceptions import PRFetcherError
from ai_pr_review.services.filter_pipeline import (
    FilterPipelineResult,
    FilterReason,
    FilterReasonCode,
    FilterResult,
)
from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
from ai_pr_review.services.result_store import ResultStore


class StubPRFetcher:
    def __init__(self, *args, **kwargs):
        self.pr = PRData(
            pr_number=42,
            title="Add authentication",
            description="desc",
            author="alice",
            state="open",
            head_sha="head123",
            base_sha="base123",
            head_ref="feature",
            base_ref="main",
            diff="diff --git a/src/app.py b/src/app.py",
            files=[
                FileDiff(
                    filename="src/app.py",
                    status=FileStatus.MODIFIED,
                    additions=3,
                    deletions=1,
                    changes=4,
                    patch="@@ -1 +1 @@\n-print('a')\n+print('b')",
                )
            ],
            url="https://github.com/owner/repo/pull/42",
            merged=False,
            owner="owner",
            repo="repo",
        )
        self.comment_body = None

    def fetch(self, pr_url: str) -> PRData:
        return self.pr

    def fetch_file_content(self, owner: str, repo: str, file_path: str, ref: str) -> str | None:
        return "def run():\n    return True\n"

    def _get_pull_request(self, owner: str, repo: str, pr_number: int):
        return self

    def create_issue_comment(self, body: str) -> None:
        self.comment_body = body


class StubFilterPipeline:
    def __init__(self, *args, **kwargs):
        pass

    def filter_pr_data(self, pr_data: PRData):
        results = [FilterResult(file=file_diff, included=True) for file_diff in pr_data.files]
        return pr_data, FilterPipelineResult(results=results)


class StubContextBuilder:
    def __init__(self, *args, **kwargs):
        pass

    def build_context(self, file_path: str, diff: str, full_content: str) -> FileContext:
        return FileContext(
            file_path=file_path,
            language="python",
            diff=diff,
            diff_with_context="@@ context 1:2 @@\n>   1: def run():",
            imports=[],
            functions=[],
            classes=[],
            parse_mode="regex",
        )


class StubPromptAssembler:
    def __init__(self, *args, **kwargs):
        pass

    def build_system_prompt(self, language: str) -> str:
        return "system"

    def build_user_prompt(self, file_context: FileContext) -> str:
        return "user"


class StubAIClient:
    def __init__(self, *args, **kwargs):
        pass

    async def review_code(self, system_prompt: str, user_prompt: str) -> ReviewResult:
        return ReviewResult(
            summary="Found one issue",
            findings=[
                Finding(
                    severity="high",
                    category="security",
                    file="src/app.py",
                    line_start=10,
                    line_end=12,
                    title="SQL injection risk",
                    problem="User input is concatenated into SQL.",
                    suggestion="Use parameterized queries.",
                    confidence=0.95,
                    code_snippet="query = f'SELECT ...'",
                )
            ],
        )


class StubPostProcessor:
    def __init__(self, *args, **kwargs):
        pass

    def process(self, result: ReviewResult) -> ReviewResult:
        return result


class StubChatProvider:
    def __init__(self, config):
        self.config = config

    async def chat(self, messages, **kwargs):
        from ai_pr_review.services.model_providers.base import ProviderResponse

        return ProviderResponse(text=f"echo: {messages[-1]['content']}")

    async def list_models(self, **kwargs):
        return ["model-a", "model-b"]


class ModelAwareChatProvider:
    def __init__(self, config):
        self.config = config

    async def chat(self, messages, **kwargs):
        from ai_pr_review.services.model_providers.base import ProviderResponse

        return ProviderResponse(text=f"{self.config.model_name}: {messages[-1]['content']}")


class FailingChatProvider:
    def __init__(self, config):
        self.config = config

    async def chat(self, messages, **kwargs):
        from ai_pr_review.services.exceptions import AIServiceError

        raise AIServiceError("模型供应商请求失败: HTTP 400 Not supported model bad-model")


class FailingDiscoveryProvider:
    def __init__(self, config):
        self.config = config

    async def list_models(self, **kwargs):
        from ai_pr_review.services.exceptions import AIServiceError

        raise AIServiceError("模型列表请求失败: HTTP 404 Not Found")


class ProbeSuccessProvider:
    def __init__(self, config):
        self.config = config

    async def chat(self, messages, **kwargs):
        from ai_pr_review.services.model_providers.base import ProviderResponse

        return ProviderResponse(text="pong")


class ProbeFailingProvider:
    def __init__(self, config):
        self.config = config

    async def chat(self, messages, **kwargs):
        from ai_pr_review.services.exceptions import AIServiceError

        raise AIServiceError("模型供应商网络请求失败。")


def install_success_stubs(monkeypatch):
    monkeypatch.setattr("ai_pr_review.cli.PRFetcher", StubPRFetcher)
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
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.AIClient", StubAIClient)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PostProcessor", StubPostProcessor
    )


def configure_temp_app(monkeypatch, tmp_path: Path, **overrides) -> AppConfig:
    config_path = tmp_path / "config.json"
    result_db_path = tmp_path / "results.db"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.result_store = ResultStoreConfig(db_path=str(result_db_path))

    for section, value in overrides.items():
        setattr(config, section, value)

    config.save(config_path, save_key=True)
    return config


def test_cli_terminal_output_success(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["https://github.com/owner/repo/pull/42"])

    assert result.exit_code == 0
    assert "AI PR Review Report" in result.output
    assert "Total Findings: 1" in result.output or (
        "问题总数" in result.output and "1" in result.output
    )
    assert "SQL injection risk" in result.output
    assert "Saved run " in result.output


def test_cli_writes_markdown_report(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()
    output_path = tmp_path / "report.md"

    result = runner.invoke(
        main,
        [
            "https://github.com/owner/repo/pull/42",
            "--format",
            "markdown",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "# AI PR Review Report" in content
    assert "### SQL injection risk" in content


def test_cli_markdown_report_includes_filter_summary_when_files_excluded(
    monkeypatch, tmp_path: Path
):
    class PartiallyExcludedFilterPipeline(StubFilterPipeline):
        def filter_pr_data(self, pr_data: PRData):
            excluded_file = FileDiff(
                filename="docs/README.md",
                status=FileStatus.MODIFIED,
                additions=1,
                deletions=0,
                changes=1,
                patch="@@ -1 +1,2 @@\n doc\n+more",
            )
            results = [
                FilterResult(file=file_diff, included=True) for file_diff in pr_data.files
            ] + [
                FilterResult(
                    file=excluded_file,
                    included=False,
                    reasons=[
                        FilterReason(
                            code=FilterReasonCode.EXCLUDED_BY_PATTERN,
                            action="exclude",
                            message="Matched a skip pattern.",
                        )
                    ],
                )
            ]
            return pr_data, FilterPipelineResult(results=results)

    install_success_stubs(monkeypatch)
    monkeypatch.setattr(orchestrator_module, "FilterPipeline", PartiallyExcludedFilterPipeline)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()
    output_path = tmp_path / "report.md"

    result = runner.invoke(
        main,
        [
            "https://github.com/owner/repo/pull/42",
            "--format",
            "markdown",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    content = output_path.read_text(encoding="utf-8")
    assert "## Filter Summary" in content
    assert "`excluded_by_pattern`: 1" in content


def test_cli_infers_json_format_from_output_extension(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()
    output_path = tmp_path / "report.json"

    result = runner.invoke(
        main,
        ["https://github.com/owner/repo/pull/42", "--output", str(output_path)],
    )

    assert result.exit_code == 0
    content = output_path.read_text(encoding="utf-8")
    assert '"total_findings": 1' in content
    assert '"repository": "owner/repo"' in content
    assert '"filter"' in content


def _report_payload_artifacts(
    *, filtered_findings: dict | None = None, findings: list[Finding] | None = None
):
    """Artifacts for `build_report_payload`, built from the shared PR stub."""
    from ai_pr_review.services.review_orchestrator import ReviewArtifacts

    pr_data = StubPRFetcher().pr
    results = [FilterResult(file=file_diff, included=True) for file_diff in pr_data.files]
    return ReviewArtifacts(
        pr_data=pr_data,
        filter_result=FilterPipelineResult(results=results),
        review_result=ReviewResult(summary="审查完成", findings=findings or []),
        total_cost=0.0124,
        duration_seconds=42.3,
        run_id="run-42",
        filtered_findings=filtered_findings or {},
    )


def test_report_payload_run_carries_the_filtered_threshold_and_counts():
    """报告载荷的 TUI 契约：`report.run.filtered.{threshold,below_threshold}`。

    见 `frontend/tui/src/empty-findings.ts`：0 findings 时它据此解释「模型给出 N 条
    候选但都低于门槛 X，已过滤」。
    """
    artifacts = _report_payload_artifacts(
        filtered_findings={
            "before": 5,
            "after": 2,
            "below_threshold": 3,
            "duplicates": 0,
            "threshold": 0.7,
            "severity_sorted": True,
        }
    )

    payload = cli_module.build_report_payload(artifacts)

    assert payload["run"]["filtered"] == {
        "threshold": 0.7,
        "below_threshold": 3,
        "duplicates": 0,
    }
    # TUI 用 `typeof value === "number"` 判定「有数据」，所以必须是真数字
    assert isinstance(payload["run"]["filtered"]["threshold"], float)
    assert isinstance(payload["run"]["filtered"]["below_threshold"], int)

    # 与评论审计行共用同一份归一化：同一个 run 的两种披露不许漂移
    from ai_pr_review.services.publish_service import comment_filter_disclosure

    disclosure = comment_filter_disclosure(artifacts.filtered_findings)
    assert payload["run"]["filtered"]["below_threshold"] == disclosure["below_threshold"]
    assert payload["run"]["filtered"]["threshold"] == disclosure["threshold"]


def test_report_payload_never_fabricates_filtered_counts():
    """没有记录到过滤统计时省略 `filtered` 键，不伪造 0 / 门槛。"""
    payload = cli_module.build_report_payload(_report_payload_artifacts())

    assert "filtered" not in payload["run"]

    # 只有部分键（旧 run 或坏数据）：只保留实测到的数字，不补门槛、不补 0
    partial = cli_module.build_report_payload(
        _report_payload_artifacts(filtered_findings={"below_threshold": 2, "duplicates": 0})
    )
    assert partial["run"]["filtered"] == {"below_threshold": 2, "duplicates": 0}

    # 一个数字都没记录 → 整块省略（而非 {"below_threshold": 0} 这种伪造陈述）
    garbage = cli_module.build_report_payload(
        _report_payload_artifacts(
            filtered_findings={"below_threshold": None, "threshold": "not-a-number"}
        )
    )
    assert "filtered" not in garbage["run"]


def test_cli_json_report_discloses_the_confidence_threshold(monkeypatch, tmp_path: Path):
    """端到端：CLI 的 `--format json` 输出（`build_report_payload`）带过滤披露。"""
    install_success_stubs(monkeypatch)
    config = configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()
    output_path = tmp_path / "report.json"

    result = runner.invoke(
        main,
        ["https://github.com/owner/repo/pull/42", "--output", str(output_path)],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["counts"]["total_findings"] == 1
    filtered = payload["run"]["filtered"]
    assert filtered["threshold"] == pytest.approx(config.post_processor.confidence_threshold)
    assert filtered["below_threshold"] == 0
    assert filtered["duplicates"] == 0


def test_cli_json_report_explains_a_zero_finding_run_filtered_by_threshold(
    monkeypatch, tmp_path: Path
):
    """端到端：候选全部低于门槛 → 0 findings，但披露仍说明被过滤了几条。"""
    install_success_stubs(monkeypatch)
    configure_temp_app(
        monkeypatch, tmp_path, post_processor=PostProcessorConfig(confidence_threshold=0.99)
    )
    runner = CliRunner()
    output_path = tmp_path / "report.json"

    result = runner.invoke(
        main,
        ["https://github.com/owner/repo/pull/42", "--output", str(output_path)],
    )

    assert result.exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    # StubAIClient 的 finding confidence=0.95 < 0.99：被门槛丢弃而不是消失
    assert payload["counts"]["total_findings"] == 0
    assert payload["run"]["filtered"]["threshold"] == pytest.approx(0.99)
    assert payload["run"]["filtered"]["below_threshold"] == 1


def test_cli_publishes_comment(monkeypatch, tmp_path: Path):
    created_fetchers: list[StubPRFetcher] = []

    def factory(*args, **kwargs):
        fetcher = StubPRFetcher(*args, **kwargs)
        created_fetchers.append(fetcher)
        return fetcher

    monkeypatch.setattr("ai_pr_review.cli.PRFetcher", factory)
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", factory)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.FilterPipeline", StubFilterPipeline
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ContextBuilder", StubContextBuilder
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PromptAssembler", StubPromptAssembler
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.AIClient", StubAIClient)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PostProcessor", StubPostProcessor
    )

    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    configure_temp_app(monkeypatch, tmp_path)
    result = runner.invoke(
        main,
        ["https://github.com/owner/repo/pull/42", "--publish-comment", "--format", "markdown"],
    )

    assert result.exit_code == 0
    assert len(created_fetchers) == 2
    body = created_fetchers[-1].comment_body
    assert body is not None
    # v2 comment: the temp config is zh-CN, so the chrome is Chinese while the
    # findings themselves stay as the model wrote them.
    assert "## 🤖 AI PR 审查报告" in body
    assert "**`owner/repo`** · [PR #42](https://github.com/owner/repo/pull/42)" in body
    assert "@alice" in body  # the PR author is carried into the target line
    assert "> **1 个问题**" in body
    assert "<summary><b>⚠️ 高风险 · 1 条</b></summary>" in body
    assert "### 📌 Review summary" not in body
    assert "# AI PR Review Report" not in body


def test_cli_publishes_a_fork_comment_with_pr_files_links(monkeypatch, tmp_path: Path):
    """P6 §4.5：fork PR 的评论不能用 blob 链接（head commit 在 fork 仓库里）。"""
    created_fetchers: list[StubPRFetcher] = []

    class ForkStubPRFetcher(StubPRFetcher):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pr = self.pr.model_copy(update={"head_repo_full_name": "contributor/repo"})

    def factory(*args, **kwargs):
        fetcher = ForkStubPRFetcher(*args, **kwargs)
        created_fetchers.append(fetcher)
        return fetcher

    monkeypatch.setattr("ai_pr_review.cli.PRFetcher", factory)
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", factory)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.FilterPipeline", StubFilterPipeline
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.ContextBuilder", StubContextBuilder
    )
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PromptAssembler", StubPromptAssembler
    )
    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.AIClient", StubAIClient)
    monkeypatch.setattr(
        "ai_pr_review.services.review_orchestrator.PostProcessor", StubPostProcessor
    )

    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    config = configure_temp_app(monkeypatch, tmp_path)
    result = runner.invoke(
        main,
        ["https://github.com/owner/repo/pull/42", "--publish-comment", "--format", "markdown"],
    )

    assert result.exit_code == 0
    body = created_fetchers[-1].comment_body
    assert body is not None
    assert "https://github.com/owner/repo/pull/42/files" in body
    assert "https://github.com/owner/repo/blob/head123" not in body

    store = ResultStore(config.result_store)
    run_id = store.list_runs(limit=1)[0]["id"]
    assert store.get_run_metadata(run_id)["fork"] == {
        "is_fork": True,
        "head_repo": "contributor/repo",
    }


def test_cli_returns_exit_code_1_on_service_error(monkeypatch, tmp_path: Path):
    class FailingPRFetcher:
        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, pr_url: str) -> PRData:
            raise PRFetcherError("boom")

    monkeypatch.setattr("ai_pr_review.services.review_orchestrator.PRFetcher", FailingPRFetcher)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["https://github.com/owner/repo/pull/42"])

    assert result.exit_code == 1
    assert "Error: boom" in result.output


def test_cli_config_show_outputs_saved_provider(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-abcd")
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="sk-test-abcd",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    # 未加 save_key=True，密钥不会被写入配置文件；save() 会就此告警。
    with pytest.warns(RuntimeWarning, match="save_key=False"):
        config.save(config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "show"])

    assert result.exit_code == 0
    assert '"name": "deepseek"' in result.output
    assert '"default_model": "deepseek-chat"' in result.output
    assert '"api_key": "sk-***abcd"' in result.output
    assert '"api_key": "sk-test-abcd"' not in result.output


def test_cli_config_init_creates_project_template(tmp_path: Path):
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "config",
            "init",
            "--provider",
            "siliconflow",
            "--directory",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    config_path = tmp_path / ".ai_pr_review" / "config.json"
    local_example_path = tmp_path / ".ai_pr_review" / "config.local.json.example"
    gitignore_path = tmp_path / ".gitignore"
    assert config_path.exists()
    assert local_example_path.exists()
    assert gitignore_path.exists()

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["provider"]["name"] == "siliconflow"
    assert payload["provider"]["base_url"] == "https://api.siliconflow.cn/v1"
    assert payload["provider"]["default_model"] == "deepseek-ai/DeepSeek-V3"
    assert "api_key" not in payload["provider"]
    # Personal runtime/profile choices belong to the user (or project-local)
    # config; a project-shared template must not pin them.
    assert "preferences" not in payload
    assert ".ai_pr_review/config.local.json" in gitignore_path.read_text(encoding="utf-8")
    assert "SILICONFLOW_API_KEY" in result.output


def test_cli_config_init_allows_custom_model_and_force(tmp_path: Path):
    runner = CliRunner()
    first = runner.invoke(
        main,
        [
            "config",
            "init",
            "--provider",
            "doubao",
            "--model",
            "custom-endpoint-model",
            "--directory",
            str(tmp_path),
        ],
    )
    second = runner.invoke(
        main,
        [
            "config",
            "init",
            "--provider",
            "doubao",
            "--model",
            "another-model",
            "--directory",
            str(tmp_path),
        ],
    )
    forced = runner.invoke(
        main,
        [
            "config",
            "init",
            "--provider",
            "doubao",
            "--model",
            "another-model",
            "--directory",
            str(tmp_path),
            "--force",
        ],
    )

    assert first.exit_code == 0
    assert second.exit_code == 1
    assert forced.exit_code == 0
    payload = json.loads((tmp_path / ".ai_pr_review" / "config.json").read_text(encoding="utf-8"))
    assert payload["provider"]["name"] == "doubao"
    assert payload["provider"]["default_model"] == "another-model"
    assert "another-model" in payload["provider"]["models"]


def test_domestic_provider_presets_are_available():
    expected = {
        "siliconflow": "SILICONFLOW_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
        "zhipu": "ZHIPUAI_API_KEY",
        "baichuan": "BAICHUAN_API_KEY",
        "minimax": "MINIMAX_API_KEY",
        "stepfun": "STEPFUN_API_KEY",
        "doubao": "ARK_API_KEY",
        "hunyuan": "HUNYUAN_API_KEY",
        "yi": "YI_API_KEY",
    }

    for provider_name, env_var in expected.items():
        provider = config_module.ModelProviderConfig.from_name(provider_name)
        assert provider.name == provider_name
        assert provider.api_format == "openai"
        assert provider.base_url.startswith("https://")
        assert config_module.MODEL_PROVIDER_PRESETS[provider_name]["env_var"] == env_var
        assert provider_name in config_module.PROVIDER_MODEL_PRESETS


def test_config_load_project_local_override_without_touching_user_config(
    monkeypatch, tmp_path: Path
):
    project_root = tmp_path / "repo"
    project_config_dir = project_root / ".ai_pr_review"
    project_config_dir.mkdir(parents=True)
    (project_root / ".git").mkdir()

    user_config_path = tmp_path / "user-config.json"
    user_config_path.write_text(
        json.dumps(
            {
                "provider": {
                    "name": "deepseek",
                    "display_name": "DeepSeek",
                    "api_key": "user-key",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_format": "openai",
                    "models": {
                        "deepseek-chat": {
                            "name": "deepseek-chat",
                            "context_window": 32768,
                            "max_output": 4096,
                        }
                    },
                    "default_model": "deepseek-chat",
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_config_dir / "config.json").write_text(
        json.dumps(
            {
                "provider": {
                    "name": "custom",
                    "display_name": "Custom Endpoint",
                    "base_url": "https://example.com/v1",
                    "api_format": "openai",
                    "models": {
                        "custom-model": {
                            "name": "custom-model",
                            "context_window": 32768,
                            "max_output": 4096,
                        }
                    },
                    "default_model": "custom-model",
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_config_dir / "config.local.json").write_text(
        json.dumps(
            {
                "provider": {"api_key": "project-local-key"},
                "preferences": {"output_format": "json", "language": "zh-CN"},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", user_config_path)
    monkeypatch.chdir(project_root)

    loaded = config_module.AppConfig.load()

    assert loaded.provider.name == "custom"
    assert loaded.provider.base_url == "https://example.com/v1"
    assert loaded.provider.api_key == "project-local-key"
    assert loaded.ai_client.api_key == "project-local-key"
    assert loaded.preferences.output_format == "json"


def test_config_load_env_api_key_overrides_file(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config_path.write_text(
        json.dumps(
            {
                "provider": {
                    "name": "custom",
                    "display_name": "Custom Endpoint",
                    "api_key": "persisted-key",
                    "base_url": "https://example.com/v1",
                    "api_format": "openai",
                    "models": {
                        "custom-model": {
                            "name": "custom-model",
                            "context_window": 32768,
                            "max_output": 4096,
                        }
                    },
                    "default_model": "custom-model",
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_PR_REVIEW_API_KEY", "env-override-key")

    loaded = config_module.AppConfig.load(config_path)

    assert loaded.provider.api_key == "env-override-key"
    assert loaded.ai_client.api_key == "env-override-key"


def test_cli_config_show_uses_custom_config_path_option(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "custom-config.json"
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="sk-test-abcd",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_path), "config", "show"])

    assert result.exit_code == 0
    assert f'"config_path": "{str(config_path).replace("\\", "\\\\")}"' in result.output
    assert '"api_key": "sk-***abcd"' in result.output


def test_cli_config_test_validates_provider(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="openrouter",
        api_key="router-key",
        model="openai/gpt-4o-mini",
        base_url="https://openrouter.ai/api/v1",
        api_format="openai",
    )
    # 未加 save_key=True，密钥不会被写入配置文件；save() 会就此告警。
    with pytest.warns(RuntimeWarning, match="save_key=False"):
        config.save(config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "test"])

    assert result.exit_code == 0
    assert "Configuration valid: provider=openrouter" in result.output


def test_cli_config_test_warns_for_custom_provider(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="custom-model",
        base_url="https://example.com/v1",
        api_format="custom",
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "test"])

    assert result.exit_code == 0
    assert "custom provider may route code through an untrusted endpoint" in result.output


def test_cli_config_test_fails_when_api_key_missing(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="custom-model",
        base_url="https://example.com/v1",
        api_format="openai",
    )
    # 显式不保存密钥：save() 应当就此告警。
    with pytest.warns(RuntimeWarning, match="save_key=False"):
        config.save(config_path, save_key=False)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "test"])

    assert result.exit_code == 1
    assert "模型供应商 API Key 未提供" in result.output
    assert "MODEL_PROVIDER_API_KEY" in result.output
    assert "AI_PR_REVIEW_API_KEY" in result.output


def test_cli_config_health_reports_provider_status(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "health"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["provider"] == "deepseek"
    assert payload["model"] == "deepseek-chat"
    assert payload["api_key_present"] is True


def test_cli_config_health_can_discover_models(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "ai_pr_review.provider_diagnostics.create_model_provider",
        lambda config: StubChatProvider(config),
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="custom-model",
        base_url="https://example.com/v1",
        api_format="openai",
    )
    config.provider = config_module.ProviderConfig.from_model_provider(
        config.ai_client.model_provider
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "health", "--discover-models"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["discovered_model_count"] == 2
    assert payload["discovered_models"] == ["model-a", "model-b"]


def test_cli_config_health_probe_reports_connectivity(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "ai_pr_review.provider_diagnostics.create_model_provider",
        lambda config: ProbeSuccessProvider(config),
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="custom-model",
        base_url="https://example.com/v1",
        api_format="openai",
    )
    config.provider = config_module.ProviderConfig.from_model_provider(
        config.ai_client.model_provider
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "health", "--probe"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["probe_ok"] is True
    assert payload["probe_response_excerpt"] == "pong"


def test_cli_config_health_probe_failure_returns_error(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "ai_pr_review.provider_diagnostics.create_model_provider",
        lambda config: ProbeFailingProvider(config),
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="custom-model",
        base_url="https://example.com/v1",
        api_format="openai",
    )
    config.provider = config_module.ProviderConfig.from_model_provider(
        config.ai_client.model_provider
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "health", "--probe"])

    assert result.exit_code == 1
    assert "Provider probe failed" in result.output


def test_cli_preferences_command_updates_preferences(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "preferences",
            "--ui-language",
            "en-US",
            "--response-language",
            "en-US",
            "--chat-layout",
            "split",
            "--output-format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ui_language"] == "en-US"
    assert payload["language"] == "en-US"
    assert payload["chat_layout"] == "split"
    assert payload["output_format"] == "json"
    assert payload["workbench_mode"] == "auto"
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["ai_client"]["api_key"] == "deepseek-key"


def test_cli_preferences_command_sets_workbench_mode(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["preferences", "--workbench", "off"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["workbench_mode"] == "off"
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["preferences"]["workbench_mode"] == "off"
    # --workbench 不该碰其他偏好，也不该把已保存的 Key 丢掉。
    assert persisted["preferences"]["chat_layout"] == "compact"
    assert persisted["ai_client"]["api_key"] == "deepseek-key"
    assert config_module.AppConfig.load(config_path).preferences.workbench_mode == "off"


def test_cli_config_preferences_alias_sets_workbench_mode(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "preferences", "--workbench", "always"])

    assert result.exit_code == 0
    assert json.loads(result.output)["workbench_mode"] == "always"
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["preferences"]["workbench_mode"] == "always"


def test_cli_preferences_command_rejects_invalid_workbench_mode(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["preferences", "--workbench", "sometimes"])

    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert not config_path.exists()


def test_cli_preferences_command_sets_repo_context(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["preferences", "--repo-context", "off"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["repo_context"] == "off"
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["preferences"]["repo_context"] == "off"
    # --repo-context 不该碰其他偏好，也不该把已保存的 Key 丢掉。
    assert persisted["preferences"]["workbench_mode"] == "auto"
    assert persisted["preferences"]["chat_layout"] == "compact"
    assert persisted["ai_client"]["api_key"] == "deepseek-key"
    assert config_module.AppConfig.load(config_path).preferences.repo_context == "off"


def test_cli_config_preferences_alias_sets_repo_context(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "preferences", "--repo-context", "tests+imports"])

    assert result.exit_code == 0
    assert json.loads(result.output)["repo_context"] == "tests+imports"
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["preferences"]["repo_context"] == "tests+imports"


def test_cli_preferences_command_rejects_invalid_repo_context(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["preferences", "--repo-context", "imports"])

    assert result.exit_code == 2
    assert "Invalid value" in result.output
    assert not config_path.exists()


def test_cli_preferences_command_toggles_symbol_locate(monkeypatch, tmp_path: Path):
    """`--no-symbol-locate` 关掉 L2 符号定位，`--symbol-locate` 再打开（一条命令即可脚本化）。"""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["preferences", "--no-symbol-locate"])

    assert result.exit_code == 0
    assert json.loads(result.output)["symbol_locate"] is False
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["preferences"]["symbol_locate"] is False
    # 不该碰其他偏好，也不该把已保存的 Key 丢掉。
    assert persisted["preferences"]["repo_context"] == "tests+imports"
    assert persisted["preferences"]["workbench_mode"] == "auto"
    assert persisted["ai_client"]["api_key"] == "deepseek-key"
    assert config_module.AppConfig.load(config_path).preferences.symbol_locate is False

    again = runner.invoke(main, ["preferences", "--symbol-locate"])

    assert again.exit_code == 0
    assert json.loads(again.output)["symbol_locate"] is True
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))["preferences"]["symbol_locate"]
        is True
    )


def test_cli_config_preferences_alias_sets_symbol_locate(monkeypatch, tmp_path: Path):
    """`pr-review config preferences` 别名同样生效（与 `--repo-context` 共用同一实现）。"""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "preferences", "--no-symbol-locate"])

    assert result.exit_code == 0
    assert json.loads(result.output)["symbol_locate"] is False
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["preferences"]["symbol_locate"] is False


def test_cli_preferences_command_echoes_symbol_locate_without_writing(
    monkeypatch, tmp_path: Path
):
    """两个开关都不传：只回显当前值（默认开启），不落盘、不创建配置文件。"""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(main, ["preferences"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["symbol_locate"] is True
    assert payload["repo_context"] == "tests+imports"
    assert not config_path.exists()


def test_cli_config_export_snapshot_carries_workbench_mode(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    export_path = tmp_path / "export.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.preferences.workbench_mode = "off"
    config.save(config_path, save_key=True)

    runner = CliRunner()
    export_result = runner.invoke(main, ["config", "export", "--output", str(export_path)])
    show_result = runner.invoke(main, ["config", "show"])

    assert export_result.exit_code == 0
    assert json.loads(export_path.read_text(encoding="utf-8"))["preferences"][
        "workbench_mode"
    ] == "off"
    assert show_result.exit_code == 0
    assert json.loads(show_result.output)["preferences"]["workbench_mode"] == "off"


def test_cli_config_quick_wizard_sets_workbench_mode(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["config", "--quick"],
        input=(
            "zh-CN\n"
            "compact\n"
            "zh-CN\n"
            "3\n"
            "deepseek-key\n"
            "1\n"
            "deepseek-chat\n"
            "32768\n"
            "4096\n"
            "ghp_123456789012345678901234567890123456\n"
            "terminal\n"
            "n\n"
            "off\n"
            "y\n"
        ),
    )

    assert result.exit_code == 0
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["preferences"]["workbench_mode"] == "off"
    assert config_module.AppConfig.load(config_path).preferences.workbench_mode == "off"


def test_cli_config_quick_wizard_keeps_existing_workbench_mode(monkeypatch, tmp_path: Path):
    """向导会整体重建 PreferencesConfig；第 2 阶段不带回该字段就会静默重置。"""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.preferences = config_module.PreferencesConfig(workbench_mode="off")
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["config", "--quick"],
        input=(
            "zh-CN\n"
            "compact\n"
            "zh-CN\n"
            "3\n"
            "deepseek-key\n"
            "1\n"
            "deepseek-chat\n"
            "32768\n"
            "4096\n"
            "ghp_123456789012345678901234567890123456\n"
            "terminal\n"
            "n\n"
            "\n"
            "y\n"
        ),
    )

    assert result.exit_code == 0
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["preferences"]["workbench_mode"] == "off"


def test_cli_chat_message_uses_configured_provider(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        cli_module, "create_model_provider", lambda config: StubChatProvider(config)
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.preferences = config_module.PreferencesConfig(
        language="zh-CN",
        ui_language="zh-CN",
        chat_layout="plain",
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["chat", "--message", "你好", "--layout", "plain"])

    assert result.exit_code == 0
    assert "Terminal Workspace" in result.output
    assert "你好" in result.output
    assert "echo: 你好" in result.output


def test_cli_chat_message_handles_provider_error(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        cli_module, "create_model_provider", lambda config: FailingChatProvider(config)
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="bad-model",
        base_url="https://example.com/v1",
        api_format="openai",
    )
    config.provider = config_module.ProviderConfig.from_model_provider(
        config.ai_client.model_provider
    )
    config.preferences = config_module.PreferencesConfig(chat_layout="plain")
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["chat", "--message", "你好", "--layout", "plain"])

    assert result.exit_code == 0
    assert "模型服务不支持当前模型" in result.output
    assert "pr-review config model --name" in result.output
    assert "Traceback" not in result.output


def test_cli_chat_slash_help_and_config(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        cli_module, "create_model_provider", lambda config: StubChatProvider(config)
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.preferences = config_module.PreferencesConfig(
        language="zh-CN",
        ui_language="zh-CN",
        chat_layout="plain",
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["chat", "--layout", "plain"], input="/help\n/config\n/exit\n")

    assert result.exit_code == 0
    assert "Commands" in result.output
    assert "/model <ID>" in result.output
    assert "/session" in result.output
    assert "Config" in result.output
    assert '"model": "deepseek-chat"' in result.output


def test_cli_chat_slash_model_switches_session_model(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        cli_module, "create_model_provider", lambda config: ModelAwareChatProvider(config)
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="old-model",
        base_url="https://example.com/v1",
        api_format="openai",
    )
    config.provider = config_module.ProviderConfig.from_model_provider(
        config.ai_client.model_provider
    )
    config.preferences = config_module.PreferencesConfig(chat_layout="plain")
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["chat", "--layout", "plain"],
        input="/model new-model\nhello\n/exit\n",
    )

    assert result.exit_code == 0
    assert "模型已切换为: new-model" in result.output
    assert "new-model: hello" in result.output


def test_cli_chat_slash_review_runs_pr_review(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    config = configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["chat", "--layout", "plain"],
        input="/review https://github.com/owner/repo/pull/42\n/exit\n",
    )

    assert result.exit_code == 0
    assert config.report_renderer.title in result.output
    assert "Total Findings: 1" in result.output or (
        "问题总数" in result.output and "1" in result.output
    )
    assert "Saved run " in result.output


def test_cli_chat_slash_history_outputs_recent_runs(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    runner.invoke(main, ["https://github.com/owner/repo/pull/42"])
    result = runner.invoke(main, ["chat", "--layout", "plain"], input="/history\n/exit\n")

    assert result.exit_code == 0
    assert "History (1)" in result.output


def test_cli_chat_slash_history_supports_limit_argument(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    runner.invoke(main, ["https://github.com/owner/repo/pull/42"])
    result = runner.invoke(main, ["chat", "--layout", "plain"], input="/history 1\n/exit\n")

    assert result.exit_code == 0
    assert "History (1)" in result.output


def test_cli_chat_slash_stats_outputs_aggregates(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    runner.invoke(main, ["https://github.com/owner/repo/pull/42"])
    result = runner.invoke(main, ["chat", "--layout", "plain"], input="/stats\n/exit\n")

    assert result.exit_code == 0
    assert "Stats" in result.output
    assert "total_runs" in result.output
    assert "1" in result.output


def test_cli_chat_slash_session_outputs_current_context(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        cli_module, "create_model_provider", lambda config: StubChatProvider(config)
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.preferences = config_module.PreferencesConfig(chat_layout="plain")
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["chat", "--layout", "plain"], input="/session\n/exit\n")

    assert result.exit_code == 0
    assert "Session" in result.output
    assert '"model": "deepseek-chat"' in result.output


def test_cli_chat_persists_and_restores_session(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        cli_module, "create_model_provider", lambda config: StubChatProvider(config)
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.preferences = config_module.PreferencesConfig(chat_layout="plain")
    config.save(config_path, save_key=True)

    runner = CliRunner()
    first = runner.invoke(main, ["chat", "--layout", "plain"], input="你好\n/exit\n")
    second = runner.invoke(main, ["chat", "--layout", "plain"], input="/restore\n/exit\n")

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "已恢复" in second.output


def test_cli_chat_clear_removes_persisted_session(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "ai_pr_review.provider_diagnostics.create_model_provider",
        lambda config: StubChatProvider(config),
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.preferences = config_module.PreferencesConfig(chat_layout="plain")
    config.save(config_path, save_key=True)

    runner = CliRunner()
    runner.invoke(main, ["chat", "--layout", "plain"], input="你好\n/exit\n")
    result = runner.invoke(main, ["chat", "--layout", "plain"], input="/clear\n/exit\n")

    assert result.exit_code == 0
    assert "会话已清空" in result.output
    assert not (tmp_path / "chat_session.json").exists()


def test_cli_config_model_updates_active_model(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="old-model",
        base_url="https://example.com/v1",
        api_format="openai",
    )
    config.provider = config_module.ProviderConfig.from_model_provider(
        config.ai_client.model_provider
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "model", "--name", "new-model"])

    assert result.exit_code == 0
    saved = config_module.AppConfig.load(config_path)
    assert saved.provider.default_model == "new-model"
    assert saved.ai_client.model == "new-model"
    assert saved.ai_client.api_key == "custom-key"


def test_cli_rejects_local_model_for_remote_provider(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    config.provider = config_module.ProviderConfig.from_model_provider(
        config_module.ModelProviderConfig.from_name("deepseek", api_key="deepseek-test-key")
    )
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-test-key",
        model="deepseek-flash",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.save(config_path, save_key=True)

    result = CliRunner().invoke(main, ["config", "model", "--name", "qwen3.5:4b"])

    assert result.exit_code != 0
    assert "本地 Ollama 模型" in result.output
    saved = config_module.AppConfig.load(config_path)
    assert saved.provider.name == "deepseek"
    assert saved.ai_client.model == "deepseek-flash"


def test_set_active_model_allows_custom_provider_model():
    config = config_module.AppConfig.from_env()
    config.provider = config_module.ProviderConfig.from_model_provider(
        config_module.ModelProviderConfig.from_name(
            "custom", api_key="custom-key", base_url="https://example.com/v1"
        )
    )
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="old-model",
        base_url="https://example.com/v1",
        api_format="openai",
    )

    cli_module._set_active_model(config, "new-model")

    assert config.ai_client.model == "new-model"
    assert config.provider.default_model == "new-model"


def test_cli_config_models_discovers_and_sets_first(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "ai_pr_review.provider_diagnostics.create_model_provider",
        lambda config: StubChatProvider(config),
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="old-model",
        base_url="https://example.com/v1",
        api_format="openai",
    )
    config.provider = config_module.ProviderConfig.from_model_provider(
        config.ai_client.model_provider
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "models", "--set-first"])

    assert result.exit_code == 0
    assert "model-a" in result.output
    saved = config_module.AppConfig.load(config_path)
    assert saved.ai_client.model == "model-a"
    assert saved.provider.default_model == "model-a"


def test_cli_config_models_failure_shows_fallback_hints(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        "ai_pr_review.provider_diagnostics.create_model_provider",
        lambda config: FailingDiscoveryProvider(config),
    )
    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="custom",
        api_key="custom-key",
        model="mimo v2.5pro",
        base_url="https://example.com/v1",
        api_format="openai",
    )
    config.provider = config_module.ProviderConfig.from_model_provider(
        config.ai_client.model_provider
    )
    config.save(config_path, save_key=True)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "models"])

    assert result.exit_code == 1
    assert "Fallback 建议" in result.output
    assert "pr-review config health --discover-models" in result.output
    assert "pr-review config model --name" in result.output


def test_cli_config_quick_wizard_saves_provider(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["config", "--quick"],
        input="zh-CN\ncompact\nzh-CN\n3\ndeepseek-key\n1\ndeepseek-chat\n32768\n4096\nghp_123456789012345678901234567890123456\nterminal\nn\n\ny\n",
    )

    assert result.exit_code == 0
    assert "AI PR Review 助手 - 配置向导" in result.output
    assert "已输入 API Key（12 个字符）" in result.output
    assert "配置完成" in result.output
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["ai_client"]["api_key"] == "deepseek-key"
    assert persisted["provider"]["api_key"] == "deepseek-key"

    saved = config_module.AppConfig.load(config_path)
    assert saved.ai_client.provider == "deepseek"
    assert saved.ai_client.api_key == "deepseek-key"
    assert saved.ai_client.model == "deepseek-chat"
    assert saved.github_token == "ghp_123456789012345678901234567890123456"
    assert saved.preferences.output_format == "terminal"
    assert saved.preferences.ui_language == "zh-CN"
    assert saved.preferences.chat_layout == "compact"
    assert saved.preferences.language == "zh-CN"


def test_cli_config_quick_wizard_no_save_key_omits_key(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    # --no-save-key 走的是不持久化密钥的路径，save() 会就此告警。
    with pytest.warns(RuntimeWarning, match="save_key=False"):
        result = runner.invoke(
            main,
            ["config", "--quick", "--no-save-key"],
            input="zh-CN\ncompact\nzh-CN\n3\ndeepseek-key\n1\ndeepseek-chat\n32768\n4096\nghp_123456789012345678901234567890123456\nterminal\nn\n\n",
        )

    assert result.exit_code == 0
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert "api_key" not in persisted["ai_client"]
    assert "api_key" not in persisted["provider"]


def test_cli_config_quick_wizard_save_key_persists_key_after_warning(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["config", "--quick", "--save-key"],
        input="zh-CN\ncompact\nzh-CN\n3\ndeepseek-key\n1\ndeepseek-chat\n32768\n4096\nghp_123456789012345678901234567890123456\nterminal\nn\n\ny\n",
    )

    assert result.exit_code == 0
    assert "已输入 API Key（12 个字符）" in result.output
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["ai_client"]["api_key"] == "deepseek-key"
    assert persisted["provider"]["api_key"] == "deepseek-key"
    assert persisted["github_token"] == "ghp_123456789012345678901234567890123456"
    assert "github_token" not in persisted["pr_fetcher"]
    assert "API Key 将以明文形式保存到配置文件" in result.output


def test_cli_config_quick_wizard_rejects_empty_github_token(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["config", "--quick"],
        input=(
            "zh-CN\n"
            "compact\n"
            "zh-CN\n"
            "3\n"
            "deepseek-key\n"
            "1\n"
            "deepseek-chat\n"
            "32768\n"
            "4096\n"
            "\n"
            "ghp_123456789012345678901234567890123456\n"
            "terminal\n"
            "n\n"
            "\n"
            "y\n"
        ),
    )

    assert result.exit_code == 0
    assert "GitHub Token 不能为空。" in result.output


def test_cli_config_quick_wizard_rejects_invalid_github_token_format(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["config", "--quick"],
        input=(
            "zh-CN\n"
            "compact\n"
            "zh-CN\n"
            "3\n"
            "deepseek-key\n"
            "1\n"
            "deepseek-chat\n"
            "32768\n"
            "4096\n"
            "github_token\n"
            "ghp_123456789012345678901234567890123456\n"
            "terminal\n"
            "n\n"
            "\n"
            "y\n"
        ),
    )

    assert result.exit_code == 0
    assert "GitHub Token 格式不正确，必须以 ghp_ 开头。" in result.output


def test_cli_config_export_and_import_roundtrip(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    export_path = tmp_path / "export.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    config = config_module.AppConfig.from_env()
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.provider = config_module.ProviderConfig.from_model_provider(
        config.ai_client.model_provider
    )
    config.github_token = "ghp_test_1234"
    config.preferences = config_module.PreferencesConfig(output_format="json", language="zh-CN")
    config.pr_fetcher.github_token = "ghp_test_1234"
    config.save(config_path, save_key=True)

    runner = CliRunner()
    export_result = runner.invoke(main, ["config", "export", "--output", str(export_path)])

    assert export_result.exit_code == 0
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["provider"]["name"] == "deepseek"
    assert exported["provider"]["api_key"] != "deepseek-key"
    assert exported["preferences"]["output_format"] == "json"

    import_payload = {
        "provider": {
            "name": "openrouter",
            "display_name": "OpenRouter",
            "api_key": "router-secret",
            "base_url": "https://openrouter.ai/api/v1",
            "api_format": "openai",
            "models": {
                "openai/gpt-4o-mini": {
                    "name": "openai/gpt-4o-mini",
                    "context_window": 128000,
                    "max_output": 16384,
                }
            },
            "default_model": "openai/gpt-4o-mini",
        },
        "github_token": "ghp_roundtrip_5678",
        "preferences": {
            "output_format": "markdown",
            "language": "en-US",
            "auto_publish_comment": True,
        },
    }
    import_source = tmp_path / "import.json"
    import_source.write_text(
        json.dumps(import_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    import_result = runner.invoke(main, ["config", "import", str(import_source), "--save-key"])

    assert import_result.exit_code == 0
    saved = config_module.AppConfig.load(config_path)
    assert saved.ai_client.provider == "openrouter"
    assert saved.ai_client.model == "openai/gpt-4o-mini"
    assert saved.ai_client.api_key == "router-secret"
    assert saved.preferences.output_format == "markdown"
    assert saved.github_token == "ghp_roundtrip_5678"


def test_config_save_persists_single_github_token_source(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    config = config_module.AppConfig.from_env()
    config.github_token = "ghp_single_source_123456789012345678901234567890"
    config.pr_fetcher.github_token = config.github_token

    config.save(config_path, save_key=True)

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["github_token"] == "ghp_single_source_123456789012345678901234567890"
    assert "github_token" not in persisted["pr_fetcher"]


def test_config_load_migrates_legacy_pr_fetcher_github_token(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    legacy_payload = {
        "provider": {
            "name": "deepseek",
            "display_name": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "api_format": "openai",
            "models": {
                "deepseek-chat": {
                    "name": "deepseek-chat",
                    "context_window": 32768,
                    "max_output": 4096,
                }
            },
            "default_model": "deepseek-chat",
        },
        "pr_fetcher": {
            "github_token": "ghp_legacy_12345678901234567890123456789012",
            "fetch_concurrency": 4,
        },
        "preferences": {
            "output_format": "terminal",
            "language": "zh-CN",
            "auto_publish_comment": False,
        },
    }
    config_path.write_text(
        json.dumps(legacy_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    saved = config_module.AppConfig.load(config_path)

    assert saved.github_token == "ghp_legacy_12345678901234567890123456789012"
    assert saved.pr_fetcher.github_token == "ghp_legacy_12345678901234567890123456789012"


def test_config_save_persists_provider_api_key_to_ai_client(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    config = config_module.AppConfig.from_env()
    config.provider = config_module.ProviderConfig(
        name="deepseek",
        display_name="DeepSeek",
        api_key="provider-only-key",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
        models={
            "deepseek-chat": config_module.ProviderModelConfig(
                name="deepseek-chat",
                context_window=32768,
                max_output=4096,
            )
        },
        default_model="deepseek-chat",
    )
    config.ai_client.api_key = ""

    config.save(config_path, save_key=True)

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["provider"]["api_key"] == "provider-only-key"
    assert persisted["ai_client"]["api_key"] == "provider-only-key"


def test_config_save_persists_ai_client_api_key_to_provider(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    config = config_module.AppConfig.from_env()
    config.provider.api_key = ""
    config.ai_client = config_module.AIClientConfig(
        provider="deepseek",
        api_key="ai-client-key",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )

    config.save(config_path, save_key=True)

    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["provider"]["api_key"] == "ai-client-key"
    assert persisted["ai_client"]["api_key"] == "ai-client-key"


def test_config_load_backfills_provider_api_key_from_ai_client(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    config_path.write_text(
        json.dumps(
            {
                "provider": {
                    "name": "deepseek",
                    "display_name": "DeepSeek",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_format": "openai",
                    "models": {
                        "deepseek-chat": {
                            "name": "deepseek-chat",
                            "context_window": 32768,
                            "max_output": 4096,
                        }
                    },
                    "default_model": "deepseek-chat",
                },
                "ai_client": {
                    "provider": "deepseek",
                    "api_key": "ai-client-only-key",
                    "model": "deepseek-chat",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_format": "openai",
                    "headers": {},
                    "extra_params": {},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    saved = config_module.AppConfig.load(config_path)

    assert saved.provider.api_key == "ai-client-only-key"
    assert saved.ai_client.api_key == "ai-client-only-key"


def test_cli_history_returns_persisted_runs(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    config = configure_temp_app(
        monkeypatch,
        tmp_path,
        report_renderer=ReportRendererConfig(title="Custom Review Title"),
    )
    runner = CliRunner()

    review_result = runner.invoke(
        main, ["https://github.com/owner/repo/pull/42", "--format", "markdown"]
    )
    history_result = runner.invoke(
        main, ["history", "--pr-url", "https://github.com/owner/repo/pull/42"]
    )

    assert review_result.exit_code == 0
    assert "# Custom Review Title" in review_result.output
    assert history_result.exit_code == 0
    payload = json.loads(history_result.output)
    assert payload["statistics"]["total_runs"] == 1
    assert len(payload["runs"]) == 1
    assert payload["runs"][0]["pr_url"] == "https://github.com/owner/repo/pull/42"
    assert payload["runs"][0]["included_files"] == 1
    assert payload["runs"][0]["excluded_files"] == 0
    assert payload["runs"][0]["model"] == config.ai_client.model


def test_cli_review_persists_result_metadata(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    config = configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["https://github.com/owner/repo/pull/42"])

    assert result.exit_code == 0
    store = ResultStore(config.result_store)
    runs = store.list_runs(limit=5)
    assert len(runs) == 1
    assert runs[0]["head_sha"] == "head123"
    assert runs[0]["total_files"] == 1
    assert runs[0]["included_files"] == 1
    assert runs[0]["excluded_files"] == 0
    assert runs[0]["total_findings"] == 1


def test_cli_only_fetch_outputs_pr_metadata(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["https://github.com/owner/repo/pull/42", "--only-fetch"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["pr"]["pr_number"] == 42
    assert payload["pr"]["title"] == "Add authentication"
    assert payload["run"]["duration_seconds"] >= 0


def test_cli_dry_run_hides_filter_reasons_by_default(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["https://github.com/owner/repo/pull/42", "--dry-run"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["run"]["dry_run"] is True
    assert payload["pr"]["files_changed"] == 1
    assert payload["filter"]["included_count"] == 1
    assert all("reasons" not in entry for entry in payload["filter"]["results"])


def test_cli_only_filter_can_show_filter_reasons(monkeypatch, tmp_path: Path):
    class ReasonedFilterPipeline(StubFilterPipeline):
        def filter_pr_data(self, pr_data: PRData):
            class Result:
                included_count = 1
                excluded_count = 0

                def to_dict(self):
                    return {
                        "total_files": 1,
                        "included_count": 1,
                        "excluded_count": 0,
                        "results": [
                            {
                                "filename": "src/app.py",
                                "included": True,
                                "reasons": [{"code": "included_by_default"}],
                            }
                        ],
                    }

            return pr_data, Result()

    install_success_stubs(monkeypatch)
    monkeypatch.setattr(orchestrator_module, "FilterPipeline", ReasonedFilterPipeline)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["https://github.com/owner/repo/pull/42", "--only-filter", "--show-filter-reasons"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["filter"]["results"][0]["reasons"][0]["code"] == "included_by_default"


def test_cli_stats_returns_aggregated_statistics(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    review_result = runner.invoke(main, ["https://github.com/owner/repo/pull/42"])
    stats_result = runner.invoke(main, ["stats"])

    assert review_result.exit_code == 0
    assert stats_result.exit_code == 0
    payload = json.loads(stats_result.output)
    assert payload["total_runs"] == 1
    assert payload["unique_prs"] == 1
    assert payload["total_findings"] == 1


def test_cli_review_explains_filter_summary_when_no_files_reviewed(monkeypatch, tmp_path: Path):
    class ExcludingFilterPipeline(StubFilterPipeline):
        def filter_pr_data(self, pr_data: PRData):
            results = [
                FilterResult(
                    file=file_diff,
                    included=False,
                    reasons=[
                        FilterReason(
                            code=FilterReasonCode.EXCLUDED_BY_PATTERN,
                            action="exclude",
                            message="Matched a skip pattern.",
                        )
                    ],
                )
                for file_diff in pr_data.files
            ]
            filtered_pr = pr_data.model_copy(update={"files": []})
            return filtered_pr, FilterPipelineResult(results=results)

    install_success_stubs(monkeypatch)
    monkeypatch.setattr(orchestrator_module, "FilterPipeline", ExcludingFilterPipeline)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["https://github.com/owner/repo/pull/42"])

    assert result.exit_code == 0
    assert "No reviewable files remained after filtering." in result.output
    assert "命中黑名单规则 1 个" in result.output


def test_cli_rejects_multiple_short_circuit_modes(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        main,
        ["https://github.com/owner/repo/pull/42", "--dry-run", "--only-fetch"],
    )

    assert result.exit_code != 0
    assert "不能同时使用" in result.output


def test_plain_chat_status_uses_active_local_slot(tmp_path: Path) -> None:
    from ai_pr_review.chat_runtime import _render_status_bar

    config = AppConfig.load(tmp_path / "config.json")
    config.preferences.hybrid_strategy = "local_only"
    config._sync_runtime_sections()

    assert cli_module._check_config_status(config)["api_key_configured"] is True
    assert "Ollama" in cli_module._chat_title(config)
    assert "qwen3.5:4b" in cli_module._chat_title(config)
    status = _render_status_bar(config, 0).plain
    assert "Ollama" in status
    assert "Anthropic" not in status


def test_explicit_tui_without_bun_reports_actionable_error(monkeypatch, tmp_path: Path) -> None:
    """A lean install without Bun or a compiled TUI must fail visibly."""
    real_exists = Path.exists
    monkeypatch.setattr(
        Path,
        "exists",
        lambda path: False if path.name == "pr-review-tui.exe" else real_exists(path),
    )
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "empty-appdata"))
    monkeypatch.delenv("BUN_EXECUTABLE", raising=False)
    assert cli_module._find_bun_runtime() is None
    monkeypatch.setenv("AI_PR_REVIEW_CONFIG", str(tmp_path / "config.json"))
    result = CliRunner().invoke(main, ["chat", "--tui"])
    assert result.exit_code != 0
    assert "OpenTUI" in result.output
    assert "Bun" in result.output
    assert "--plain" in result.output


def test_export_run_rebuilds_markdown_and_json_from_history(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    config = config_module.AppConfig.from_env()
    from ai_pr_review.models.pr_data import PRData
    from ai_pr_review.services.prompt_assembler import Finding, ReviewResult
    from ai_pr_review.services.result_store import ResultStore

    config.result_store = ResultStoreConfig(db_path=str(tmp_path / "results.db"))
    result = ReviewResult(
        summary="stored summary",
        findings=[
            Finding(
                severity="high",
                category="安全性",
                file="a.py",
                line_start=1,
                line_end=1,
                title="t",
                problem="p",
                suggestion="s",
                confidence=0.9,
                code_snippet="x",
            )
        ],
    )
    run_id = ResultStore(config.result_store).save_result(
        "https://github.com/o/r/pull/9",
        result,
        head_sha="sha",
        total_files=2,
        included_files=1,
        excluded_files=1,
        model="qwen3.5:4b",
    )
    md = tmp_path / "report.md"
    js = tmp_path / "report.json"
    runner = CliRunner()
    assert (
        runner.invoke(
            main,
            [
                "--config",
                str(config_path),
                "export-run",
                run_id,
                "--format",
                "markdown",
                "--output",
                str(md),
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            main,
            [
                "--config",
                str(config_path),
                "export-run",
                run_id,
                "--format",
                "json",
                "--output",
                str(js),
            ],
        ).exit_code
        == 0
    )
    assert "stored summary" in md.read_text(encoding="utf-8")
    assert (
        json.loads(js.read_text(encoding="utf-8"))["result"]["findings"][0]["category"]
        == "security"
    )


def test_plain_chat_disables_reasoning_for_local_provider(monkeypatch):
    import asyncio

    from ai_pr_review.config import ModelProviderConfig, ProviderConfig
    from ai_pr_review.services.model_providers.base import ProviderResponse

    config = AppConfig.from_env()
    config.local_provider = ProviderConfig.from_model_provider(
        ModelProviderConfig.from_name("ollama", model_name="qwen3.5:4b")
    )
    config.preferences.hybrid_strategy = "local_only"
    config._sync_runtime_sections()

    captured = {}

    class FakeProvider:
        async def chat(self, messages, **kwargs):
            captured.update(kwargs)
            return ProviderResponse(text="本地模型正常")

    monkeypatch.setattr(cli_module, "create_model_provider", lambda config: FakeProvider())
    result = asyncio.run(
        cli_module._send_chat_message(config, [{"role": "user", "content": "hi"}])
    )

    assert result == "本地模型正常"
    assert captured["reasoning_effort"] == "none"


# ---------------------------------------------------------------------------
# §12.3 demo / showcase payloads
# ---------------------------------------------------------------------------

# SHA-256 of `pr-review demo --json-output` taken from the pre-refactor CLI
# (`git show HEAD:src/ai_pr_review/cli.py`) through CliRunner. The payload
# builder moved into `services/demo_runner.py`; the printed bytes must not.
# Newlines are LF here because CliRunner captures text, not OS-translated bytes.
#
# P6 (§3.3) added the server-side `Finding.rule_id` field, so payloads that carry
# findings gained exactly one key: stripping `rule_id` from the current payload
# reproduces the original hashes (`sql-injection` 91e9948d…, `tls-disabled`
# d277f194…, `clean-change` d1245bae… unchanged because it has no findings).
# 2026-09-27 有意更新：规划依据不再内嵌规范 id（`Detected risk categories: security, …`）。
# 类别/策略本来就是独立字段，由前端按 id 查词典渲染成「安全 / Security」，写进句子
# 等于同一套词汇在前后端各存一份。三个 case 的其余字段逐字未变（已逐字段核对），
# demo 的默认语言也刻意保持 en —— 这份 JSON 是 `--json-output` 的冻结契约。
DEMO_JSON_SHA256 = {
    "sql-injection": "b6961aef43111a8f73d7d84f27d4530b87e9cd17f9c3feb477d2f5e1d4c488a3",
    "tls-disabled": "4b079f3fb6aa1e9d3a8933347aa762a6fb59302212941d89a04d396d5ac1f34d",
    "clean-change": "9e895a866ea21a217e62317d72b1cc9a91d1ef2958b8ec5a8dd9f5913340a347",
}

# Literal copy of the showcase payload the CLI printed before the refactor.
SHOWCASE_PAYLOAD_GOLDEN = {
    "title": "AI PR Review Assistant · Competition Showcase",
    "offline_ready": True,
    "real_review_ready": False,
    "steps": [
        {"step": 1, "command": "pr-review doctor", "purpose": "检查本地运行环境与凭据状态"},
        {
            "step": 2,
            "command": "pr-review demo --case sql-injection",
            "purpose": "离线展示规则、规划与证据校验",
        },
        {
            "step": 3,
            "command": "pr-review plan <PR_URL>",
            "purpose": "生成真实 PR 审查计划，不调用模型",
        },
        {"step": 4, "command": "pr-review <PR_URL> --verbose", "purpose": "执行完整 AI 审查并落库"},
        {"step": 5, "command": "pr-review history", "purpose": "复盘结果、成本与人工反馈"},
    ],
}


@pytest.mark.parametrize("case_key", sorted(DEMO_JSON_SHA256))
def test_demo_json_output_is_byte_identical_to_the_shared_builder(case_key):
    """`--json-output` must keep printing exactly what it did before §12.3."""
    from ai_pr_review.services.demo_runner import demo_case_payload

    result = CliRunner().invoke(main, ["demo", "--case", case_key, "--json-output"])

    assert result.exit_code == 0
    expected = json.dumps(demo_case_payload(case_key), ensure_ascii=False, indent=2) + "\n"
    assert result.output == expected
    assert hashlib.sha256(result.output.encode("utf-8")).hexdigest() == DEMO_JSON_SHA256[case_key]


def test_demo_json_output_is_deterministic_across_runs():
    first = CliRunner().invoke(main, ["demo", "--case", "sql-injection", "--json-output"])
    second = CliRunner().invoke(main, ["demo", "--case", "sql-injection", "--json-output"])
    assert first.output == second.output


def test_demo_json_output_carries_case_plan_and_findings():
    result = CliRunner().invoke(main, ["demo", "--case", "sql-injection", "--json-output"])
    payload = json.loads(result.output)

    # The backend `/demo` payload is this object plus `text` (§12.3): the key
    # set here is what the TUI's demo panel consumes.
    assert sorted(payload) == ["case", "findings", "plan"]
    assert payload["case"]["key"] == "sql-injection"
    assert payload["findings"]
    assert payload["plan"]["risk_level"]


def test_demo_list_cases_still_prints_one_line_per_case():
    result = CliRunner().invoke(main, ["demo", "--list-cases"])
    lines = result.output.strip().splitlines()

    assert result.exit_code == 0
    assert len(lines) == 3
    assert lines[0].startswith("sql-injection: ")


def test_demo_console_path_reports_the_run_result():
    result = CliRunner().invoke(main, ["demo", "--case", "sql-injection"])

    assert result.exit_code == 0
    assert "Demo result" in result.output
    assert "Risk level:" in result.output
    assert "Evidence validated:" in result.output


def test_showcase_json_output_is_byte_identical_to_the_shared_builder(tmp_path):
    """With an unconfigured workspace, `--json-output` must be unchanged (§12.3)."""
    from ai_pr_review.config import AppConfig
    from ai_pr_review.services.showcase_runner import showcase_payload

    config_path = tmp_path / "config.json"
    result = CliRunner().invoke(main, ["--config", str(config_path), "showcase", "--json-output"])

    assert result.exit_code == 0
    expected = (
        json.dumps(showcase_payload(AppConfig.load(config_path)), ensure_ascii=False, indent=2)
        + "\n"
    )
    assert result.output == expected


def test_showcase_json_output_matches_the_frozen_payload(tmp_path):
    """Byte-level pin against the payload the CLI emitted before the refactor."""
    result = CliRunner().invoke(
        main, ["--config", str(tmp_path / "config.json"), "showcase", "--json-output"]
    )

    assert result.exit_code == 0
    assert result.output == json.dumps(SHOWCASE_PAYLOAD_GOLDEN, ensure_ascii=False, indent=2) + "\n"


def test_showcase_real_review_ready_needs_both_api_key_and_github_token(tmp_path):
    """`real_review_ready` follows the workspace config, not a constant."""
    config_path = tmp_path / "config.json"
    config = AppConfig.from_env()
    config.ai_client.api_key = "test-key"
    config.preferences.hybrid_strategy = "remote_only"
    config._sync_runtime_sections()
    config.save(config_path, save_key=True)

    only_key = CliRunner().invoke(main, ["--config", str(config_path), "showcase", "--json-output"])
    assert only_key.exit_code == 0
    assert json.loads(only_key.output)["real_review_ready"] is False  # no GitHub token

    with_token = AppConfig.load(config_path)
    with_token.github_token = "test-token"
    with_token.pr_fetcher.github_token = "test-token"
    with_token.save(config_path, save_key=True)

    both = CliRunner().invoke(main, ["--config", str(config_path), "showcase", "--json-output"])
    assert both.exit_code == 0
    assert json.loads(both.output)["real_review_ready"] is True


def test_cli_review_records_pr_title_for_later_publishing(monkeypatch, tmp_path: Path):
    """§12.2: `/publish` can only render a real PR title if the run stored one."""
    install_success_stubs(monkeypatch)
    config = configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["https://github.com/owner/repo/pull/42"])

    assert result.exit_code == 0
    store = ResultStore(config.result_store)
    run_id = store.list_runs(limit=1)[0]["id"]
    assert store.get_run_metadata(run_id)["pr_title"] == "Add authentication"


def test_demo_and_showcase_never_touch_the_network(monkeypatch):
    """§12.3: both commands are strictly offline — no model call, no GitHub call."""
    import ai_pr_review.services.pr_fetcher as pr_fetcher_module
    import ai_pr_review.services.model_providers.factory as factory_module

    def _explode(*args, **kwargs):
        raise AssertionError("offline command attempted a network client")

    monkeypatch.setattr(pr_fetcher_module, "PRFetcher", _explode)
    monkeypatch.setattr(factory_module, "create_model_provider", _explode)

    runner = CliRunner()
    for args in (
        ["demo", "--case", "sql-injection", "--json-output"],
        ["demo", "--case", "sql-injection"],
        ["demo", "--list-cases"],
        ["showcase", "--json-output"],
        ["showcase"],
    ):
        result = runner.invoke(main, args)
        assert result.exit_code == 0, (args, result.output, result.exception)


# ---------------------------------------------------------------------------
# 模型规格的 CLI 出口（设计 §4.1-D；原在 test_jsonl_backend.py，改用全局 --config 跑真实 CLI）
# ---------------------------------------------------------------------------


def test_config_show_and_export_keep_model_specs(tmp_path: Path) -> None:
    """中转站规格能导出、能在 `config show`（脱敏）里回显——不改产品代码的回归。"""
    config_path = tmp_path / "config.json"
    config = AppConfig.from_env()
    config.ai_client = AIClientConfig(
        provider="custom",
        api_key="relay-key",
        model="relay-model",
        base_url="https://relay.example.com/v1",
        api_format="openai",
    )
    config.provider = ProviderConfig.from_model_provider(config.ai_client.model_provider)
    config.provider.set_model_spec("relay-model", context_window=200_000, max_output=16_384)
    config._sync_runtime_sections()
    config.save(config_path, save_key=True)

    runner = CliRunner()
    shown = runner.invoke(main, ["--config", str(config_path), "config", "show"])
    assert shown.exit_code == 0
    shown_payload = json.loads(shown.output)
    assert shown_payload["provider"]["models"]["relay-model"]["context_window"] == 200_000
    assert shown_payload["provider"]["models"]["relay-model"]["max_output"] == 16_384

    export_path = tmp_path / "export.json"
    exported = runner.invoke(
        main, ["--config", str(config_path), "config", "export", "--output", str(export_path)]
    )
    assert exported.exit_code == 0
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    assert payload["provider"]["models"]["relay-model"]["context_window"] == 200_000
    assert payload["provider"]["models"]["relay-model"]["max_output"] == 16_384


def test_config_import_round_trips_a_relay_spec(tmp_path: Path) -> None:
    """导入含规格的中转站配置后落盘同值（`save` 重建 provider 的路上不能丢）。"""
    config_path = tmp_path / "config.json"
    import_payload = {
        "provider": {
            "name": "custom",
            "display_name": "Custom Endpoint",
            "api_key": "relay-key",
            "base_url": "https://relay.example.com/v1",
            "api_format": "openai",
            "models": {
                "relay-model": {
                    "name": "relay-model",
                    "context_window": 200_000,
                    "max_output": 16_384,
                }
            },
            "default_model": "relay-model",
        },
        "preferences": {"output_format": "terminal", "language": "zh-CN"},
    }
    import_source = tmp_path / "import.json"
    import_source.write_text(
        json.dumps(import_payload, ensure_ascii=False), encoding="utf-8"
    )

    result = CliRunner().invoke(
        main, ["--config", str(config_path), "config", "import", str(import_source), "--save-key"]
    )

    assert result.exit_code == 0
    saved = AppConfig.load(config_path)
    assert saved.provider.models["relay-model"].context_window == 200_000
    assert saved.provider.models["relay-model"].max_output == 16_384


def test_config_import_ignores_unknown_preference_keys(tmp_path: Path) -> None:
    """向前兼容：导入"更新版本导出的"配置时，本版本不认识的 preferences 键必须被忽略。

    `config export` 每次都写全量 preferences，所以新版本导出的文件里一定有旧版本没有的
    键；不过滤的话 `PreferencesConfig(**payload)` 直接 `TypeError`，用户连导入都做不了
    （既有缺陷，见 docs/claude-backend-followup.md §3）。
    """
    config_path = tmp_path / "config.json"
    import_payload = {
        "provider": {
            "name": "custom",
            "display_name": "Custom Endpoint",
            "api_key": "relay-key",
            "base_url": "https://relay.example.com/v1",
            "api_format": "openai",
            "models": {"relay-model": {"name": "relay-model"}},
            "default_model": "relay-model",
        },
        "preferences": {
            "output_format": "json",
            "language": "en",
            # 假装这是"下一个版本"新增的偏好项
            "future_preference_from_a_newer_release": {"enabled": True},
        },
    }
    import_source = tmp_path / "import.json"
    import_source.write_text(
        json.dumps(import_payload, ensure_ascii=False), encoding="utf-8"
    )

    result = CliRunner().invoke(
        main,
        ["--config", str(config_path), "config", "import", str(import_source), "--save-key"],
    )

    assert result.exit_code == 0, (result.output, result.exception)
    saved = AppConfig.load(config_path)
    # 认识的键照旧生效，不认识的键不进配置对象、也不落盘。
    assert saved.preferences.output_format == "json"
    assert saved.preferences.language == "en"
    assert "future_preference_from_a_newer_release" not in saved.preferences.__dict__


def test_config_health_reports_the_effective_spec_and_source(tmp_path: Path) -> None:
    """§3.4：`config health` 的 JSON 多四个键；不联网时如实报 builtin/unknown。"""
    config_path = tmp_path / "config.json"
    config = AppConfig.from_env()
    config.ai_client = AIClientConfig(
        provider="deepseek",
        api_key="deepseek-key",
        model="deepseek-flash",
        base_url="https://api.deepseek.com/v1",
        api_format="openai",
    )
    config.provider = ProviderConfig.from_model_provider(config.ai_client.model_provider)
    config.save(config_path, save_key=True)

    result = CliRunner().invoke(main, ["--config", str(config_path), "config", "health"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    # 预设表里有 deepseek-flash 但进程里没有目录 → builtin（不是 models.dev）。
    assert payload["spec_source"] == "builtin"
    assert (payload["context_window"], payload["max_output"]) == (1_048_576, 384_000)
    assert payload["needs_verification"] is False

    # 不在预设表里的模型（既有用例用的 deepseek-chat 就是这一类）→ unknown。
    second = AppConfig.load(config_path)
    second.provider.default_model = "deepseek-chat"
    second.provider.ensure_default_model_present()
    second._sync_runtime_sections()
    second.save(config_path, save_key=True)
    result = CliRunner().invoke(main, ["--config", str(config_path), "config", "health"])

    payload = json.loads(result.output)
    assert payload["spec_source"] == "unknown"
    assert (payload["context_window"], payload["max_output"]) == (32_768, 4_096)
