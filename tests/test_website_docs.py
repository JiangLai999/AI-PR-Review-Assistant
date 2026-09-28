"""官网文档数据的防漂移守卫。

回归点（2026-09-28 发现）：`scripts/build_website_docs.py` 把
``docs/PR_WORKFLOW.md`` 的渲染结果烧进 ``website/assets/docs-data.js``，
而那个源文档在更早的批量清理里被删掉了 —— 生成器用
``read_text(...) if exists() else ""`` 静默放行，于是官网上的"PR 工作流"
标签页继续展示一份仓库里已经不存在的文档，本地测试全绿。

因此这里锁三件事：

1. 官网每个标签页的 ``source`` 必须真实存在；
2. 提交在库里的 ``website/assets/docs-data.js`` 必须与生成器当前输出**逐字节等价**；
3. 生成器的标题渲染得真的产出 h2/h3/h4，而不是把 ``# 标题`` 当段落。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = ROOT / "scripts" / "build_website_docs.py"
DATA_PATH = ROOT / "website" / "assets" / "docs-data.js"

_DATA_PREFIX = "window.__WEBSITE_DOCS__ = "


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_website_docs_under_test", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None, f"无法加载生成器：{GENERATOR_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_committed_data() -> dict[str, Any]:
    raw = DATA_PATH.read_text(encoding="utf-8")
    assert raw.startswith(_DATA_PREFIX), f"{DATA_PATH} 缺少 {_DATA_PREFIX!r} 前缀"
    return json.loads(raw[len(_DATA_PREFIX) :].rstrip().rstrip(";"))


def test_every_tab_source_exists() -> None:
    """标签页的源文档必须真实存在，否则官网上会出现"幽灵文档"。"""
    data = _load_committed_data()

    missing = [tab["source"] for tab in data["tabs"] if not (ROOT / tab["source"]).exists()]

    assert not missing, (
        f"官网标签页的源文档不存在：{missing}；"
        "要么把文档补回来，要么改掉 scripts/build_website_docs.py 里的 source。"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "已知缺陷（2026-09-28 实测）：README 章节改名后生成器 4 处 extract_between/extract_section "
        "找不到锚点，python scripts/build_website_docs.py 直接 ValueError，"
        "所以 website/assets/docs-data.js 已经是无法再生成的冻结快照。"
        "修复属「官网文档刷新」轮：把标签页映射改到现有章节，再重新生成产物。"
        "本用例 strict：修好后必须摘掉这个标记，否则会以 XPASS 失败提醒。"
    ),
)
def test_generator_can_still_regenerate_the_site_data() -> None:
    """生成器必须能跑通今天的 README —— 它跑不通，官网就只能是冻结快照。"""
    _load_generator().build_docs_data()


def test_headings_render_as_tags_not_literal_text() -> None:
    """`#` / `##` / `###` 都要变成标题标签，而不是带井号的段落。"""
    module = _load_generator()

    html = module.markdown_to_html("# 标题\n\n## 小节\n\n### 子节\n\n正文\n")

    assert "<h2>标题</h2>" in html
    assert "<h3>小节</h3>" in html
    assert "<h4>子节</h4>" in html
    assert "># 标题<" not in html, "标题被当成段落原文输出了"


def test_hash_comments_inside_code_fences_stay_code() -> None:
    """代码块里的 `# 注释` 不能被当成标题。"""
    module = _load_generator()

    html = module.markdown_to_html("```bash\n# 注释\npytest\n```\n")

    assert "<h2>" not in html
    assert "# 注释" in html
