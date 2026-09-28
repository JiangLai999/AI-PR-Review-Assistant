from __future__ import annotations

import json

from click.testing import CliRunner

from ai_pr_review.cli import main
from ai_pr_review.demo_fixtures import get_demo_case, list_demo_cases


def test_demo_fixtures_are_shared_and_have_distinct_cases() -> None:
    cases = list_demo_cases()
    assert {case.key for case in cases} >= {"sql-injection", "tls-disabled", "clean-change"}
    assert get_demo_case("sql-injection").pr_data.files


def test_demo_json_supports_case_selection() -> None:
    result = CliRunner().invoke(main, ["demo", "--case", "tls-disabled", "--json-output"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["case"]["key"] == "tls-disabled"
    assert payload["findings"]
    assert payload["findings"][0]["evidence_status"] == "valid"


def test_demo_lists_cases() -> None:
    result = CliRunner().invoke(main, ["demo", "--list-cases"])
    assert result.exit_code == 0, result.output
    assert "sql-injection" in result.output
    assert "clean-change" in result.output


def test_doctor_json_reports_demo_and_web_readiness() -> None:
    result = CliRunner().invoke(main, ["doctor", "--json-output"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    checks = {item["key"]: item for item in payload["checks"]}
    assert checks["demo"]["ok"] is True
    assert checks["web"]["ok"] is True
    assert checks["sqlite"]["ok"] is True


def test_plan_help_exposes_json_mode() -> None:
    result = CliRunner().invoke(main, ["plan", "--help"])
    assert result.exit_code == 0
    assert "--json-output" in result.output


def test_trace_help_is_available() -> None:
    result = CliRunner().invoke(main, ["trace", "--help"])
    assert result.exit_code == 0
    assert "timing trace" in result.output


def test_showcase_json_exposes_competition_path() -> None:
    result = CliRunner().invoke(main, ["showcase", "--json-output"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["offline_ready"] is True
    assert len(payload["steps"]) == 5
    assert payload["steps"][1]["command"].startswith("pr-review demo")


def test_chat_url_extractor_accepts_markdown_and_embedded_text() -> None:
    from ai_pr_review.cli import _extract_github_pr_url

    url = "https://github.com/JiangLai999/AI-PR-Review-Assistant/pull/31"
    assert _extract_github_pr_url(f"帮我审查：[{url}]({url})") == url
    assert _extract_github_pr_url(f"pr-review {url}") == url


def test_showcase_help_exposes_interactive_mode() -> None:
    result = CliRunner().invoke(main, ["showcase", "--help"])
    assert result.exit_code == 0
    assert "--interactive" in result.output
