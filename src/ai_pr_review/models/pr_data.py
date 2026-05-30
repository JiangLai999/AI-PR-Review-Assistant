"""PR 相关数据模型。

使用 Pydantic 定义 PR 数据、文件差异和 URL 解析结果的结构。
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class FileStatus(str, Enum):
    """文件变更状态。"""

    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"
    COPIED = "copied"
    CHANGED = "changed"


class FileDiff(BaseModel):
    """单个文件的差异信息。"""

    filename: str = Field(description="文件路径（相对于仓库根目录）")
    previous_filename: str | None = Field(default=None, description="重命名前的文件路径")
    status: FileStatus = Field(description="变更状态")
    additions: int = Field(default=0, description="新增行数")
    deletions: int = Field(default=0, description="删除行数")
    changes: int = Field(default=0, description="总变更行数")
    patch: str | None = Field(default=None, description="统一 diff 格式的补丁内容")
    raw_url: str | None = Field(default=None, description="文件原始内容 URL")
    blob_url: str | None = Field(default=None, description="文件的 blob URL")

    @property
    def is_deletion_only(self) -> bool:
        return self.additions == 0 and self.deletions > 0

    def is_too_large(self, max_lines: int = 500) -> bool:
        """判断变更是否过大。"""
        return self.changes > max_lines

    @property
    def extension(self) -> str:
        return self.filename.rsplit(".", 1)[-1].lower() if "." in self.filename else ""


class PRData(BaseModel):
    """PR 完整数据。"""

    pr_number: int = Field(description="PR 编号")
    title: str = Field(description="PR 标题")
    description: str | None = Field(default=None, description="PR 描述（body）")
    author: str = Field(description="PR 作者 GitHub 用户名")
    state: str = Field(description="PR 状态（open/closed/merged）")

    head_sha: str = Field(description="PR 源分支最新 commit SHA")
    base_sha: str = Field(description="PR 目标分支最新 commit SHA")
    head_ref: str = Field(description="源分支名称")
    base_ref: str = Field(description="目标分支名称")

    diff: str = Field(default="", description="完整 unified diff 文本")
    files: list[FileDiff] = Field(default_factory=list, description="变更文件列表")

    url: str = Field(description="PR 的 HTML URL")
    created_at: datetime | None = Field(default=None, description="PR 创建时间")
    updated_at: datetime | None = Field(default=None, description="PR 最后更新时间")
    merged: bool = Field(default=False, description="是否已合并")

    owner: str = Field(description="仓库所有者")
    repo: str = Field(description="仓库名称")

    @property
    def repo_full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def total_additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def total_deletions(self) -> int:
        return sum(f.deletions for f in self.files)

    @property
    def total_changes(self) -> int:
        return sum(f.changes for f in self.files)

    @property
    def changed_files_count(self) -> int:
        return len(self.files)


class ParsedPRUrl(BaseModel):
    """从 GitHub PR URL 解析出的结果。"""

    owner: str = Field(description="仓库所有者")
    repo: str = Field(description="仓库名称")
    pr_number: int = Field(description="PR 编号")
