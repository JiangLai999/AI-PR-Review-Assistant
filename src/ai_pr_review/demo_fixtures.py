from dataclasses import dataclass

from ai_pr_review.models.pr_data import FileDiff, FileStatus, PRData


@dataclass(frozen=True)
class DemoCase:
    key: str
    title: str
    description: str
    pr_data: PRData
    file_contents: dict[str, str]


def _case_sql_injection() -> DemoCase:
    file = FileDiff(
        filename="src/auth.py",
        status=FileStatus.MODIFIED,
        additions=1,
        deletions=0,
        changes=1,
        patch='@@ -1,1 +1,2 @@\n old\n+query = f"SELECT * FROM users WHERE id={user_id}"',
    )
    return DemoCase(
        key="sql-injection",
        title="SQL injection in authentication query",
        description="Dynamic SQL built from user-controlled input.",
        pr_data=PRData(
            pr_number=1,
            title="Fix authentication query",
            description="Review a changed authentication query.",
            author="demo",
            state="open",
            head_sha="demo-head",
            base_sha="demo-base",
            head_ref="demo",
            base_ref="main",
            files=[file],
            url="https://github.com/demo/repo/pull/1",
            owner="demo",
            repo="repo",
        ),
        file_contents={"src/auth.py": 'old\nquery = f"SELECT * FROM users WHERE id={user_id}"\n'},
    )


def _case_tls() -> DemoCase:
    file = FileDiff(
        filename="src/client.py",
        status=FileStatus.MODIFIED,
        additions=1,
        deletions=0,
        changes=1,
        patch="@@ -1,1 +1,2 @@\n old\n+response = requests.get(url, verify=False)",
    )
    return DemoCase(
        key="tls-disabled",
        title="TLS verification disabled",
        description="A client disables certificate verification.",
        pr_data=PRData(
            pr_number=2,
            title="Update remote client",
            description="Change HTTP client behavior.",
            author="demo",
            state="open",
            head_sha="demo-head",
            base_sha="demo-base",
            head_ref="demo",
            base_ref="main",
            files=[file],
            url="https://github.com/demo/repo/pull/2",
            owner="demo",
            repo="repo",
        ),
        file_contents={"src/client.py": "old\nresponse = requests.get(url, verify=False)\n"},
    )


def _case_clean() -> DemoCase:
    file = FileDiff(
        filename="docs/README.md",
        status=FileStatus.MODIFIED,
        additions=1,
        deletions=0,
        changes=1,
        patch="@@ -1,1 +1,2 @@\n old\n+Document the review workflow.",
    )
    return DemoCase(
        key="clean-change",
        title="Documentation-only change",
        description="A clean change should not create security findings.",
        pr_data=PRData(
            pr_number=3,
            title="Document workflow",
            description="Improve documentation.",
            author="demo",
            state="open",
            head_sha="demo-head",
            base_sha="demo-base",
            head_ref="demo",
            base_ref="main",
            files=[file],
            url="https://github.com/demo/repo/pull/3",
            owner="demo",
            repo="repo",
        ),
        file_contents={"docs/README.md": "old\nDocument the review workflow.\n"},
    )


_CASES = {case.key: case for case in (_case_sql_injection(), _case_tls(), _case_clean())}


def list_demo_cases() -> list[DemoCase]:
    return list(_CASES.values())


def get_demo_case(key: str) -> DemoCase:
    try:
        return _CASES[key]
    except KeyError as exc:
        choices = ", ".join(_CASES)
        raise ValueError(f"Unknown demo case '{key}'. Choose one of: {choices}") from exc
