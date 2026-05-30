"""CLI entry module tests."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import ai_pr_review.cli as cli_module
import ai_pr_review.config as config_module
import ai_pr_review.services.review_orchestrator as orchestrator_module
from ai_pr_review.cli import main
from ai_pr_review.config import AppConfig, ReportRendererConfig, ResultStoreConfig
from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData
from ai_pr_review.services.context_builder import FileContext
from ai_pr_review.services.exceptions import PRFetcherError
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
        class Result:
            included_count = 1
            excluded_count = 0

            def to_dict(self):
                return {
                    "total_files": 1,
                    "included_count": 1,
                    "excluded_count": 0,
                    "results": [],
                }

        return pr_data, Result()


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
    assert "Total Findings: 1" in result.output
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


def test_cli_markdown_report_includes_filter_summary_when_files_excluded(monkeypatch, tmp_path: Path):
    class PartiallyExcludedFilterPipeline(StubFilterPipeline):
        def filter_pr_data(self, pr_data: PRData):
            class Result:
                total_files = 1
                included_count = 1
                excluded_count = 1

                @property
                def excluded_reason_counts(self):
                    return {"excluded_by_pattern": 1}

                def excluded_reason_counts(self):
                    return {"excluded_by_pattern": 1}

                def to_dict(self):
                    return {
                        "total_files": 1,
                        "included_count": 1,
                        "excluded_count": 1,
                        "excluded_reason_counts": {"excluded_by_pattern": 1},
                        "results": [],
                    }

            return pr_data, Result()

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


def test_cli_publishes_comment(monkeypatch):
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
    with runner.isolated_filesystem():
        temp_dir = Path.cwd()
        configure_temp_app(monkeypatch, temp_dir)
        result = runner.invoke(
            main,
            ["https://github.com/owner/repo/pull/42", "--publish-comment", "--format", "markdown"],
        )

    assert result.exit_code == 0
    assert len(created_fetchers) == 2
    assert created_fetchers[-1].comment_body is not None
    assert "## 🤖 AI PR Review Report" in created_fetchers[-1].comment_body
    assert "| Total Findings | 1 |" in created_fetchers[-1].comment_body
    assert "### High Findings" in created_fetchers[-1].comment_body
    assert "# AI PR Review Report" not in created_fetchers[-1].comment_body


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
    config.save(config_path, save_key=False)

    runner = CliRunner()
    result = runner.invoke(main, ["config", "test"])

    assert result.exit_code == 1
    assert "模型供应商 API Key 未提供" in result.output
    assert "MODEL_PROVIDER_API_KEY" in result.output
    assert "AI_PR_REVIEW_API_KEY" in result.output


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
    persisted = json.loads(config_path.read_text(encoding="utf-8"))
    assert persisted["ai_client"]["api_key"] == "deepseek-key"


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
    assert "AI PR Review Chat" in result.output
    assert "You: 你好" in result.output
    assert "Assistant: echo: 你好" in result.output


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
    assert "Chat Commands" in result.output
    assert "/model <模型ID>" in result.output
    assert "Chat Config" in result.output
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
    assert "Active model set to: new-model" in result.output
    assert "Assistant: new-model: hello" in result.output


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
    assert "Total Findings: 1" in result.output
    assert "Saved run " in result.output


def test_cli_chat_slash_history_outputs_recent_runs(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    runner.invoke(main, ["https://github.com/owner/repo/pull/42"])
    result = runner.invoke(main, ["chat", "--layout", "plain"], input="/history\n/exit\n")

    assert result.exit_code == 0
    assert "History" in result.output
    assert '"pr_url": "https://github.com/owner/repo/pull/42"' in result.output


def test_cli_chat_slash_stats_outputs_aggregates(monkeypatch, tmp_path: Path):
    install_success_stubs(monkeypatch)
    configure_temp_app(monkeypatch, tmp_path)
    runner = CliRunner()

    runner.invoke(main, ["https://github.com/owner/repo/pull/42"])
    result = runner.invoke(main, ["chat", "--layout", "plain"], input="/stats\n/exit\n")

    assert result.exit_code == 0
    assert "Stats" in result.output
    assert '"total_runs": 1' in result.output


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


def test_cli_config_models_discovers_and_sets_first(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        cli_module, "create_model_provider", lambda config: StubChatProvider(config)
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


def test_cli_config_quick_wizard_saves_provider(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(cli_module, "DEFAULT_CONFIG_PATH", config_path)

    runner = CliRunner()
    result = runner.invoke(
        main,
        ["config", "--quick"],
        input="zh-CN\ncompact\nzh-CN\n3\ndeepseek-key\n1\ndeepseek-chat\n32768\n4096\nghp_123456789012345678901234567890123456\nterminal\nn\ny\n",
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
    result = runner.invoke(
        main,
        ["config", "--quick", "--no-save-key"],
        input="zh-CN\ncompact\nzh-CN\n3\ndeepseek-key\n1\ndeepseek-chat\n32768\n4096\nghp_123456789012345678901234567890123456\nterminal\nn\n",
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
        input="zh-CN\ncompact\nzh-CN\n3\ndeepseek-key\n1\ndeepseek-chat\n32768\n4096\nghp_123456789012345678901234567890123456\nterminal\nn\ny\n",
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
    assert payload["filter"]["results"] == []


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
            class Result:
                included_count = 0
                excluded_count = 1

                @property
                def included_files(self):
                    return []

                @property
                def excluded_results(self):
                    return [
                        type(
                            "FilterResult",
                            (),
                            {
                                "primary_reason": type(
                                    "Reason",
                                    (),
                                    {"code": type("Code", (), {"value": "excluded_by_pattern"})()},
                                )(),
                            },
                        )()
                    ]

                def excluded_reason_counts(self):
                    return {"excluded_by_pattern": 1}

                def to_dict(self):
                    return {
                        "total_files": 1,
                        "included_count": 0,
                        "excluded_count": 1,
                        "excluded_reason_counts": {"excluded_by_pattern": 1},
                        "results": [],
                    }

            filtered_pr = pr_data.model_copy(update={"files": []})
            return filtered_pr, Result()

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
