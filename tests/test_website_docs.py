"""官网文档数据的防漂移守卫。

回归点（2026-09-28 发现）：`scripts/build_website_docs.py` 把
``README.md`` / ``docs/API.md`` / ``docs/PR_WORKFLOW.md`` 的章节渲染进
``website/assets/docs-data.js``，但：

1. 一次文档改名让 4 处章节锚点（"配置优先级"/"必需环境变量"/"配置模型供应商"/
   "代码结构"）全部失效，生成器直接 ValueError，产物退化成"无法再生成的冻结快照"；
2. 生成器用 ``read_text(...) if exists() else ""`` 静默放行缺失的源文档，
   官网会继续展示仓库里已经不存在的"幽灵文档"；
3. 内置渲染器不认表格，README「支持的模型供应商」那张表会渲染成竖线段落。

因此这里锁四件事：

1. 生成器能跑通今天的文档，且提交在库里的 ``website/assets/docs-data.js``
   与它当前输出**逐字一致**；
2. 官网每个标签页的 ``source`` 必须真实存在；
3. 生成器的标题渲染得真的产出 h2/h3/h4，而不是把 ``# 标题`` 当段落；
4. 表格只在"表头行 + 分隔行"齐全时渲染成 ``<table>``。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

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


def test_generator_can_still_regenerate_the_site_data() -> None:
    """生成器必须能跑通今天的 README —— 它跑不通，官网就只能是冻结快照。"""
    _load_generator().build_docs_data()


def test_committed_data_matches_generator_output() -> None:
    """库里的 docs-data.js 必须等于生成器当前输出，不能是冻结快照。"""
    module = _load_generator()
    expected = module.build_docs_data()

    assert _load_committed_data() == expected, (
        "website/assets/docs-data.js 与 build_docs_data() 的输出不一致；"
        "改过生成器映射或源文档后，请重跑 python scripts/build_website_docs.py 并提交产物。"
    )
    assert DATA_PATH.read_text(encoding="utf-8") == module.render_docs_data(
        expected
    ), "产物连字节都对不上（格式/空白被手改过）；请用生成器覆写，不要手改这个文件。"


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


def test_blockquote_renders_as_blockquote() -> None:
    """连续 `>` 行渲染成 blockquote，且不吞掉后面的段落。"""
    module = _load_generator()

    html = module.markdown_to_html("> 第一行\n> 第二行\n\n正文\n")

    assert "<blockquote><p>第一行 第二行</p></blockquote>" in html
    assert "<p>正文</p>" in html
    assert "&gt;" not in html, "引用块被当成普通段落，官网上会露出字面量 '>'"


def test_bold_renders_as_strong_outside_code_only() -> None:
    """`**粗体**` → `<strong>`；但代码段里的 `**` 必须保持字面量。"""
    module = _load_generator()

    html = module.markdown_to_html("普通 **加粗** 文本\n")
    assert "<strong>加粗</strong>" in html
    assert "**加粗**" not in html

    code = module.markdown_to_html("`**x**` 保持字面量\n")
    assert "<code>**x**</code>" in code
    assert "<strong>" not in code


def test_inline_link_renders_as_anchor() -> None:
    """`[文本](链接)` → `<a>`，否则官网会显示原始 markdown 文本。"""
    module = _load_generator()

    html = module.markdown_to_html("见 [docs/API.md](docs/API.md)。\n")
    assert '<a href="docs/API.md" target="_blank" rel="noopener">docs/API.md</a>' in html
    assert "](" not in html

    external = module.markdown_to_html("[GitHub](https://github.com/JiangLai999)\n")
    assert '<a href="https://github.com/JiangLai999"' in external


def test_inline_link_inside_code_span_stays_literal() -> None:
    """代码段里的 `[x](y)` 不能被渲染成锚点。"""
    module = _load_generator()

    html = module.markdown_to_html("`[x](y)`\n")
    assert "<a " not in html
    assert "[x](y)" in html


def test_unsafe_link_scheme_stays_literal() -> None:
    """`javascript:` 这类协议不能进入 href，只按字面量保留。"""
    module = _load_generator()

    html = module.markdown_to_html("[click](javascript:void)\n")
    assert "<a " not in html
    assert "javascript:void" in html


def test_relative_doc_links_are_rewritten_to_repo_blob() -> None:
    """给定 source_path 时，相对链接要指回仓库文件（官网目录里没有这些文件）。"""
    module = _load_generator()

    html = module.markdown_to_html(
        "见 [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。\n",
        source_path="docs/COMPLIANCE_AND_ORIGINALITY.md",
    )
    assert (
        'href="https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/THIRD_PARTY_NOTICES.md"'
        in html
    )
    assert "<code>../THIRD_PARTY_NOTICES.md</code>" in html

    readme = module.markdown_to_html("[`docs/API.md`](docs/API.md)\n", source_path="README.md")
    assert "/blob/main/docs/API.md" in readme


def test_table_with_delimiter_renders_as_table() -> None:
    """表头行 + `|---|---|` 分隔行 → `<table>`，单元格只做转义与反引号转 <code>。"""
    module = _load_generator()

    html = module.markdown_to_html(
        "| 供应商 | 说明 |\n"
        "|--------|------|\n"
        "| OpenAI | `gpt-4` 系列 |\n"
        "| Anthropic | Claude 系列 |\n"
    )

    assert "<table><thead><tr><th>供应商</th><th>说明</th></tr></thead><tbody>" in html
    assert "<tr><td>OpenAI</td><td><code>gpt-4</code> 系列</td></tr>" in html
    assert "<tr><td>Anthropic</td><td>Claude 系列</td></tr>" in html
    assert "</tbody></table>" in html
    # 表格必须包在可横向滚动的容器里：窄屏下不能让表格撑破文档面板。
    assert html.startswith('<div class="docs-table-wrap"><table>')
    assert html.endswith("</tbody></table></div>")


def test_table_without_delimiter_stays_paragraph() -> None:
    """没有分隔行的竖线行不得解析成表格，否则普通文本会被吞成表格。"""
    module = _load_generator()

    html = module.markdown_to_html("| 供应商 | 说明 |\n| OpenAI | 无分隔行 |\n")

    assert "<table>" not in html
    assert "<p>| 供应商 | 说明 |</p>" in html


def test_supported_providers_tab_is_rendered_as_a_table() -> None:
    """README「支持的模型供应商」是表格章节，产物里必须真的是一张表。"""
    tabs = _load_generator().build_docs_data()["tabs"]

    provider_tab = next(tab for tab in tabs if tab["id"] == "provider-config")

    assert "<table>" in provider_tab["html"]
    assert "<th>供应商</th>" in provider_tab["html"]
    assert "<td>OpenAI</td>" in provider_tab["html"]
