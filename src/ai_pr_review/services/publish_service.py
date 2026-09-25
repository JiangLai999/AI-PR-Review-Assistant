"""Two-phase GitHub publishing for a stored review run (contract §12.2).

The command is deliberately split in two:

* **preview** answers "what would be posted where" from the local SQLite
  history only. It never constructs a GitHub client and never performs a
  network write.
* **confirm** performs the single `create_issue_comment` call and reports what
  actually happened.

Every failure mode maps onto one of :data:`PUBLISH_ERROR_CODES`, so the JSONL
backend can hand the code straight to the TUI without re-interpreting strings.
"""

from __future__ import annotations

from collections.abc import Collection, MutableSet, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import PrivateAttr

from ai_pr_review.config import AppConfig
from ai_pr_review.models.pr_data import PRData
from ai_pr_review.services.exceptions import InvalidPRURLError
from ai_pr_review.services.pr_fetcher import PRFetcher
from ai_pr_review.services.report_renderer import GitHubCommentMeta, ReportRenderer
from ai_pr_review.services.result_store import ResultStore
from ai_pr_review.utils.github_url_parser import ParsedPRUrl, parse_pr_url

#: Error codes the `publish` command may return (contract §12.2).
PUBLISH_ERROR_CODES = (
    "missing_credentials",
    "not_found",
    "not_publishable",
    "publish_failed",
    "invalid_request",
)

USAGE = "用法：/publish [run_id] [--confirm]"

#: Historical runs stored no PR title, and a run never stored its author
#: (contract §12.2). Both are reported as explicit placeholders: inventing a
#: title or naming a contributor who never touched the PR would be a lie that
#: ends up in a published GitHub comment.
UNKNOWN_PR_TITLE = ""
UNKNOWN_PR_AUTHOR = "unknown"
UNKNOWN_PR_STATE = "unknown"

_MISSING_CREDENTIALS_MESSAGE = (
    "未配置 GitHub Token，无法发布评论。请运行 `pr-review config` 配置 GitHub Token 后重试。"
)

#: Appended whenever the same run is published twice in one session. The second
#: comment is still created — the ledger warns, it never skips silently.
REPEAT_PUBLISH_WARNING = "注意：该 Run 在本会话中已发布过一次，再次确认会再创建一条评论。"


class PublishError(Exception):
    """A publish failure carrying the JSONL error code for the caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _StoredRunPRData(PRData):
    """`PRData` rebuilt from a stored run, with the file count that run recorded.

    `ReportRenderer.render_github_comment` reads `changed_files_count`, which is
    derived from the per-file list. The database stores only the aggregate, and
    a fabricated empty file list would render "Files Changed: 0" for every
    historical run, so the recorded count is served through the same property.
    """

    _files_changed: int = PrivateAttr(default=0)

    @property
    def changed_files_count(self) -> int:
        return self._files_changed


@dataclass(frozen=True)
class PublishTarget:
    """Everything a publish needs, resolved from the local history."""

    run_id: str
    owner: str
    repo: str
    pr_number: int
    url: str
    comment_body: str
    findings: int

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_publish_args(args: Sequence[Any]) -> tuple[str, bool]:
    """Split `[<run_id>] [--confirm]` into `(run_id, confirm)`.

    Anything else is an `invalid_request`: guessing which unknown flag was meant
    to mean "publish for real" would risk posting a comment the user did not ask
    for.
    """
    run_id = ""
    confirm = False
    for raw in args:
        token = str(raw).strip()
        if not token:
            continue
        if token.lower() in {"--confirm", "-c"}:
            confirm = True
        elif token.startswith("-"):
            raise PublishError("invalid_request", f"无法识别的参数：{token}。{USAGE}")
        elif run_id:
            raise PublishError("invalid_request", f"只能指定一个 Run ID。{USAGE}")
        else:
            run_id = token
    return run_id, confirm


def _github_token(config: AppConfig) -> str:
    resolver = getattr(config, "_resolve_github_token", None)
    token = resolver() if callable(resolver) else ""
    return str(token or "").strip()


def _as_float(value: Any) -> float | None:
    """SQLite hands back REAL/None; anything unusable becomes None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_count(value: Any) -> int | None:
    """SQLite hand-back for the file counts; None means "not recorded"."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _stored_run_pr_data(
    run: dict[str, Any],
    metadata: dict[str, Any],
    parsed: ParsedPRUrl,
    pr_url: str,
) -> PRData:
    """Rebuild the PR view the GitHub comment renderer needs.

    Only fields the run actually recorded are filled in; the rest are the
    documented placeholders. The comment body itself is derived from the stored
    findings and summary, so nothing here is invented.
    """
    title = str(metadata.get("pr_title") or UNKNOWN_PR_TITLE)
    try:
        total_files = int(run.get("total_files") or 0)
    except (TypeError, ValueError):
        total_files = 0
    pr_data = _StoredRunPRData(
        pr_number=int(run.get("pr_number") or parsed.pr_number),
        title=title,
        description=None,
        author=UNKNOWN_PR_AUTHOR,
        state=UNKNOWN_PR_STATE,
        head_sha=str(run.get("head_sha") or ""),
        base_sha="",
        head_ref="",
        base_ref="",
        diff="",
        files=[],
        url=pr_url,
        merged=False,
        owner=parsed.owner,
        repo=parsed.repo,
    )
    # Private attributes are not constructor arguments in pydantic v2.
    pr_data._files_changed = max(0, total_files)
    return pr_data


class PublishService:
    """Resolve a stored run into a comment, preview it, or actually post it."""

    def __init__(self, config: AppConfig, *, store: ResultStore | None = None) -> None:
        self.config = config
        self._store = store

    @property
    def store(self) -> ResultStore:
        if self._store is None:
            self._store = ResultStore(self.config.result_store)
        return self._store

    # ------------------------------------------------------------------
    # Target resolution
    # ------------------------------------------------------------------
    def resolve_run_id(self, run_id: str, current_report: dict[str, Any] | None) -> str:
        """The run to publish: the explicit id, else the session's current report."""
        requested = str(run_id or "").strip()
        if requested:
            return requested
        report_run = (current_report or {}).get("run")
        if isinstance(report_run, dict):
            from_report = str(report_run.get("id") or "").strip()
            if from_report:
                return from_report
        raise PublishError(
            "invalid_request",
            "当前会话还没有审查报告，无法发布评论。请先运行 /review <PR URL>，"
            "或用 /publish <run_id> 指定历史 Run。",
        )

    def load_target(self, run_id: str, current_report: dict[str, Any] | None) -> PublishTarget:
        """Build the publish target, or raise the matching :class:`PublishError`.

        Order matters: the target's own problems (`not_found`,
        `not_publishable`) are reported before the machine's missing token,
        because configuring a token would not make an unknown or non-GitHub run
        publishable.
        """
        resolved = self.resolve_run_id(run_id, current_report)
        run = self.store.get_run_summary(resolved)
        result = self.store.get_result(resolved) if run is not None else None
        if run is None or result is None:
            raise PublishError("not_found", f"未找到审查记录：{resolved}")

        pr_url = str(run.get("pr_url") or "").strip()
        try:
            parsed = parse_pr_url(pr_url)
        except InvalidPRURLError as exc:
            raise PublishError(
                "not_publishable",
                f"该 Run 的 PR 链接不是 GitHub PR URL（{pr_url or '空'}），无法发布评论。",
            ) from exc

        if not _github_token(self.config):
            raise PublishError("missing_credentials", _MISSING_CREDENTIALS_MESSAGE)

        pr_data = _stored_run_pr_data(run, self.store.get_run_metadata(resolved), parsed, pr_url)
        comment_body = ReportRenderer(self.config.report_renderer).render_github_comment(
            result,
            pr_data,
            meta=GitHubCommentMeta(
                language=getattr(self.config.preferences, "ui_language", "zh-CN"),
                run_id=resolved,
                model=str(run.get("model") or ""),
                duration_seconds=_as_float(run.get("duration_seconds")),
                cost=_as_float(run.get("total_cost")),
                head_sha=str(run.get("head_sha") or ""),
                # A republished historical run must not look freshly reviewed.
                reviewed_at=str(run.get("created_at") or ""),
                files_reviewed=_as_count(run.get("included_files")),
                files_skipped=_as_count(run.get("excluded_files")),
                # Fork detection needs the head repository, which PRData does
                # not carry yet (see docs/claude-p5-comment-format.md F1).
                from_fork=False,
            ),
        )
        return PublishTarget(
            run_id=resolved,
            owner=parsed.owner,
            repo=parsed.repo,
            pr_number=parsed.pr_number,
            url=pr_url,
            comment_body=comment_body,
            findings=len(result.findings),
        )

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------
    def preview(
        self,
        *,
        run_id: str = "",
        current_report: dict[str, Any] | None = None,
        published_run_ids: Collection[str] | None = None,
    ) -> dict[str, Any]:
        """Return exactly what `publish` would post — without touching GitHub."""
        target = self.load_target(run_id, current_report)
        return _preview_payload(target, _already_published(target, published_run_ids))

    def publish(
        self,
        *,
        run_id: str = "",
        current_report: dict[str, Any] | None = None,
        published_run_ids: MutableSet[str] | None = None,
    ) -> dict[str, Any]:
        """Post the comment, then record the run in the session's ledger.

        The ledger is only updated after the post succeeded: a failed publish
        must not make the next attempt claim the run was already commented on.
        """
        target = self.load_target(run_id, current_report)
        already_published = _already_published(target, published_run_ids)
        self._post_comment(target)
        if published_run_ids is not None:
            published_run_ids.add(target.run_id)
        return _published_payload(target, already_published)

    def _post_comment(self, target: PublishTarget) -> None:
        """The only place in this module that talks to GitHub."""
        try:
            fetcher = PRFetcher(
                github_token=_github_token(self.config),
                config=self.config.pr_fetcher,
            )
            pull_request = fetcher._get_pull_request(target.owner, target.repo, target.pr_number)
            pull_request.create_issue_comment(target.comment_body)
        except Exception as exc:  # noqa: BLE001 - one honest code for any upstream failure
            raise PublishError(
                "publish_failed",
                f"发布评论失败：{exc}",
            ) from exc


def _already_published(target: PublishTarget, published_run_ids: Collection[str] | None) -> bool:
    if published_run_ids is None:
        return False
    return target.run_id in published_run_ids


def _preview_payload(target: PublishTarget, already_published: bool) -> dict[str, Any]:
    text = (
        f"预览：将向 {target.repository}#{target.pr_number} 发布审查评论"
        f"（{len(target.comment_body)} 字符）。再次执行 /publish --confirm 才会真正发布。"
    )
    if already_published:
        text = f"{text}\n{REPEAT_PUBLISH_WARNING}"
    return {
        "status": "preview",
        "requires_confirmation": True,
        "run_id": target.run_id,
        "repository": target.repository,
        "pr_number": target.pr_number,
        "url": target.url,
        "comment_body": target.comment_body,
        "comment_chars": len(target.comment_body),
        "findings": target.findings,
        "already_published": already_published,
        "text": text,
    }


def _published_payload(target: PublishTarget, already_published: bool) -> dict[str, Any]:
    text = (
        f"已向 {target.repository}#{target.pr_number} 发布审查评论"
        f"（{len(target.comment_body)} 字符）：{target.url}"
    )
    if already_published:
        text = f"{text}\n{REPEAT_PUBLISH_WARNING}"
    return {
        "status": "published",
        "run_id": target.run_id,
        "repository": target.repository,
        "pr_number": target.pr_number,
        "url": target.url,
        "comment_body": target.comment_body,
        "comment_chars": len(target.comment_body),
        "findings": target.findings,
        "already_published": already_published,
        "text": text,
    }
