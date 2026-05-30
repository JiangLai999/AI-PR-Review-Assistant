"""共享 pytest fixtures 和测试工具。"""

from datetime import datetime

import pytest


@pytest.fixture
def valid_pr_url() -> str:
    return "https://github.com/test-owner/test-repo/pull/42"


@pytest.fixture
def valid_pr_url_http() -> str:
    return "http://github.com/test-owner/test-repo/pull/42"


@pytest.fixture
def valid_pr_url_with_trailing() -> str:
    return "https://github.com/test-owner/test-repo/pull/42/files"


@pytest.fixture
def invalid_pr_urls() -> list[str]:
    return [
        "",
        "not-a-url",
        "https://github.com",
        "https://github.com/owner",
        "https://github.com/owner/repo",
        "https://github.com/owner/repo/pull",
        "https://github.com/owner/repo/pull/abc",
        "https://gitlab.com/owner/repo/-/merge_requests/42",
    ]


@pytest.fixture
def mock_pr_data_dict() -> dict:
    return {
        "pr_number": 42,
        "title": "Add new feature",
        "description": "This PR adds a new feature for processing requests.",
        "author": "test-user",
        "state": "open",
        "head_sha": "abc123def456",
        "base_sha": "789xyz012uvw",
        "head_ref": "feature-branch",
        "base_ref": "main",
        "diff": "diff --git a/file.py b/file.py\n@@ -1,3 +1,4 @@\n line1\n line2\n+line3\n",
        "files": [],
        "url": "https://github.com/test-owner/test-repo/pull/42",
        "created_at": datetime(2026, 5, 29, 10, 0, 0),
        "updated_at": datetime(2026, 5, 29, 12, 0, 0),
        "merged": False,
        "owner": "test-owner",
        "repo": "test-repo",
    }


@pytest.fixture
def mock_file_diff_dicts() -> list[dict]:
    return [
        {
            "filename": "src/main.py",
            "previous_filename": None,
            "status": "modified",
            "additions": 10,
            "deletions": 3,
            "changes": 13,
            "patch": "@@ -1,3 +1,10 @@\n line1\n line2\n+new line3\n+new line4\n",
            "raw_url": "https://github.com/owner/repo/raw/main/src/main.py",
            "blob_url": "https://github.com/owner/repo/blob/main/src/main.py",
        },
        {
            "filename": "tests/test_main.py",
            "previous_filename": None,
            "status": "added",
            "additions": 50,
            "deletions": 0,
            "changes": 50,
            "patch": "@@ -0,0 +1,50 @@\n+import unittest\n+...\n",
            "raw_url": "https://github.com/owner/repo/raw/main/tests/test_main.py",
            "blob_url": "https://github.com/owner/repo/blob/main/tests/test_main.py",
        },
        {
            "filename": "docs/README.md",
            "previous_filename": None,
            "status": "modified",
            "additions": 0,
            "deletions": 5,
            "changes": 5,
            "patch": "@@ -10,5 +10,0 @@\n-removed line\n-removed line\n",
            "raw_url": None,
            "blob_url": None,
        },
    ]
