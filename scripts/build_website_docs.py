from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
API_DOC = ROOT / "docs" / "API.md"
WORKFLOW_DOC = ROOT / "docs" / "PR_WORKFLOW.md"
COMPLIANCE_DOC = ROOT / "docs" / "COMPLIANCE_AND_ORIGINALITY.md"
NOTICES_DOC = ROOT / "THIRD_PARTY_NOTICES.md"
OUTPUT = ROOT / "website" / "assets" / "docs-data.js"

DATA_PREFIX = "window.__WEBSITE_DOCS__ = "

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_TABLE_ROW_RE = re.compile(r"^\|.*\|$")
# 分隔行只由 `-` 和对其冒号组成；缺了它，竖线行只是普通段落。
_TABLE_DELIMITER_RE = re.compile(r"^\|(?:\s*:?-+:?\s*\|)+$")
# 顶层章节之间的分隔线（README 用 `---`）：是版面分隔，不是章节正文。
_SECTION_SEPARATORS = {"---", "***", "___"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def require_text(path: Path) -> str:
    """必读源文档：缺失即失败，避免官网上架"幽灵文档"。"""
    if not path.exists():
        raise FileNotFoundError(f"Source document not found: {path}")
    return read_text(path)


def extract_section(markdown: str, heading: str, level: int = 2) -> str:
    """取 ``level`` 级标题 ``heading`` 的正文，到下一个同级或更高级标题为止。

    逐行扫描并跳过围栏代码块：README 的安装/使用示例整段都是 ``# 注释`` 行，
    用正则直接找章节边界会把这些注释当成标题，把正文截断在第一段代码里。
    """
    lines = markdown.replace("\r\n", "\n").split("\n")
    start: int | None = None
    end = len(lines)
    in_code_block = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        match = _HEADING_RE.match(stripped)
        if match is None:
            continue

        current_level = len(match.group(1))
        if start is None:
            if current_level == level and match.group(2) == heading:
                start = index + 1
        elif current_level <= level:
            end = index
            break

    if start is None:
        raise ValueError(f"Section not found: {heading}")

    body_lines = "\n".join(lines[start:end]).strip().split("\n")
    while body_lines and body_lines[-1].strip() in _SECTION_SEPARATORS:
        body_lines.pop()
    return "\n".join(body_lines).strip()


def inline_format(text: str) -> str:
    """行内格式：反引号 → ``<code>``，``**粗体**`` → ``<strong>``。

    代码段优先：先按反引号切分，粗体只在**代码段之外**生效 ——
    否则 `` `**x**` ``（文档里按字面量写）会被误渲染成强调。
    """
    text = html.escape(text)
    rendered: list[str] = []
    for part in re.split(r"(`[^`]+`)", text):
        if len(part) > 2 and part.startswith("`") and part.endswith("`"):
            rendered.append(f"<code>{part[1:-1]}</code>")
        else:
            rendered.append(re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", part))
    return "".join(rendered)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _render_cells(line: str, tag: str) -> str:
    return "".join(f"<{tag}>{inline_format(cell)}</{tag}>" for cell in _split_table_row(line))


def render_table(header_line: str, body_lines: list[str]) -> str:
    """表头行 + 表体行渲染成 ``<table>``。

    单元格只做 html.escape 与反引号转 ``<code>``，不解析其它行内 markdown。
    """
    head = _render_cells(header_line, "th")
    body = "".join(f"<tr>{_render_cells(line, 'td')}</tr>" for line in body_lines)
    # 外面套一层可横向滚动的容器：窄屏下宁可让表格自己滚，也不要撑破文档面板。
    return (
        '<div class="docs-table-wrap">'
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        "</div>"
    )


def markdown_to_html(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").split("\n")
    parts: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("```"):
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            parts.append(
                '<div class="code-block"><pre><code>'
                + html.escape("\n".join(code_lines))
                + "</code></pre></div>"
            )
            i += 1
            continue

        # 表格：`| a | b |` 表头行 + 紧随其后的 `|---|---|` 分隔行。
        # 没有分隔行的竖线行不算表格，继续走下面的段落分支。
        if (
            _TABLE_ROW_RE.match(stripped)
            and i + 1 < len(lines)
            and _TABLE_DELIMITER_RE.match(lines[i + 1].strip())
        ):
            header_line = stripped
            i += 2
            body_lines: list[str] = []
            while i < len(lines) and _TABLE_ROW_RE.match(lines[i].strip()):
                body_lines.append(lines[i].strip())
                i += 1
            parts.append(render_table(header_line, body_lines))
            continue

        if stripped.startswith("### "):
            parts.append(f"<h4>{inline_format(stripped[4:])}</h4>")
            i += 1
            continue

        # 引用块：连续的 `>` 行合并成一个 blockquote（README 的「注意」段落
        # 与 PR_WORKFLOW 都用到）。落进段落分支的话，官网上会显示字面量 ">"。
        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            body = " ".join(line for line in quote_lines if line)
            parts.append(f"<blockquote><p>{inline_format(body)}</p></blockquote>")
            continue

        # 只支持到 ### 的话，`# 标题` / `## 小节` 会落进下面的段落分支，
        # 在官网上渲染成字面量 "<p># 标题</p>"。docs/PR_WORKFLOW.md 整篇
        # 都是这种标题，所以这里补上 h2/h3。
        if stripped.startswith("## "):
            parts.append(f"<h3>{inline_format(stripped[3:])}</h3>")
            i += 1
            continue

        if stripped.startswith("# "):
            parts.append(f"<h2>{inline_format(stripped[2:])}</h2>")
            i += 1
            continue

        if re.match(r"^\d+\.\s+", stripped):
            items: list[str] = []
            while i < len(lines):
                current = lines[i].strip()
                if not re.match(r"^\d+\.\s+", current):
                    break
                items.append(re.sub(r"^\d+\.\s+", "", current))
                i += 1
            parts.append(
                "<ol>" + "".join(f"<li>{inline_format(item)}</li>" for item in items) + "</ol>"
            )
            continue

        if stripped.startswith("- "):
            items: list[str] = []
            while i < len(lines):
                current = lines[i].strip()
                if not current.startswith("- "):
                    break
                items.append(current[2:])
                i += 1
            parts.append(
                "<ul>" + "".join(f"<li>{inline_format(item)}</li>" for item in items) + "</ul>"
            )
            continue

        paragraph_lines = [stripped]
        i += 1
        while i < len(lines):
            current = lines[i].strip()
            if (
                not current
                or current.startswith(("```", "### ", "## ", "# ", "- ", ">"))
                or re.match(r"^\d+\.\s+", current)
                or _TABLE_ROW_RE.match(current)
            ):
                break
            paragraph_lines.append(current)
            i += 1
        parts.append(f"<p>{inline_format(' '.join(paragraph_lines))}</p>")

    return "\n".join(parts)


def build_docs_data() -> dict:
    readme = read_text(README)
    api_doc = read_text(API_DOC)
    workflow_doc = read_text(WORKFLOW_DOC) if WORKFLOW_DOC.exists() else ""
    compliance_doc = require_text(COMPLIANCE_DOC)
    require_text(NOTICES_DOC)

    tabs = [
        {
            "id": "quickstart",
            "label": "快速开始",
            "title": "README · 快速开始",
            "source": "README.md",
            "html": markdown_to_html(extract_section(readme, "快速开始")),
        },
        {
            "id": "cli-command-reference",
            "label": "CLI 命令速查",
            "title": "API 文档 · 命令概览",
            "source": "docs/API.md",
            "html": markdown_to_html(extract_section(api_doc, "命令概览")),
        },
        {
            # id 保持不变（官网用 tab.id 选中），章节已随 README 改名为「配置文件」，
            # 其中的「配置加载与覆盖规则」就是原来的「配置优先级」。
            "id": "config-priority",
            "label": "配置文件",
            "title": "README · 配置文件",
            "source": "README.md",
            "html": markdown_to_html(extract_section(readme, "配置文件")),
        },
        {
            # README 已无「必需环境变量」章节，环境要求（含 GITHUB_TOKEN）现落在 API 文档。
            "id": "env",
            "label": "环境要求",
            "title": "API 文档 · 环境要求",
            "source": "docs/API.md",
            "html": markdown_to_html(extract_section(api_doc, "环境要求")),
        },
        {
            "id": "provider-config",
            "label": "Provider 配置",
            "title": "README · 支持的模型供应商",
            "source": "README.md",
            "html": markdown_to_html(extract_section(readme, "支持的模型供应商")),
        },
        {
            # 「使用」是「快速开始」下的三级标题，所以要按 level=3 取。
            "id": "usage",
            "label": "使用示例",
            "title": "README · 使用",
            "source": "README.md",
            "html": markdown_to_html(extract_section(readme, "使用", level=3)),
        },
        {
            "id": "chat-workspace",
            "label": "Chat 工作区",
            "title": "README · Chat 工作区",
            "source": "README.md",
            "html": markdown_to_html(extract_section(readme, "Chat 工作区")),
        },
        {
            "id": "web-workbench",
            "label": "Web 工作台",
            "title": "README · Web 工作台",
            "source": "README.md",
            "html": markdown_to_html(extract_section(readme, "Web 工作台", level=3)),
        },
        {
            "id": "cli-api",
            "label": "CLI 详解",
            "title": "API 文档 · 主命令、子命令与参数",
            "source": "docs/API.md",
            "html": markdown_to_html(
                extract_section(api_doc, "主命令")
                + "\n\n"
                + extract_section(api_doc, "审查规划与反馈命令")
                + "\n\n"
                + extract_section(api_doc, "配置命令")
                + "\n\n"
                + extract_section(api_doc, "工作台与辅助命令")
                + "\n\n"
                + extract_section(api_doc, "历史命令")
            ),
        },
        {
            "id": "project-structure",
            "label": "项目结构",
            "title": "README · 项目结构",
            "source": "README.md",
            "html": markdown_to_html(extract_section(readme, "项目结构")),
        },
        {
            "id": "workflow-guide",
            "label": "PR 工作流",
            "title": "PR Workflow Guide",
            "source": "docs/PR_WORKFLOW.md",
            "html": markdown_to_html(workflow_doc),
        },
        {
            # 合规与许可：只取声明类章节（许可/权属/第三方权利/原创性/免责），
            # 跳过项目定位与提交前清单等过程性文字。
            "id": "compliance",
            "label": "合规与许可",
            "title": "合规、原创性与第三方许可",
            "source": "docs/COMPLIANCE_AND_ORIGINALITY.md",
            "html": markdown_to_html(
                "\n\n".join(
                    f"## {title}\n\n{extract_section(compliance_doc, title)}"
                    for title in (
                        "二、许可声明",
                        "三、团队主导与 AI 辅助的边界",
                        "四、团队权属声明",
                        "五、第三方权利归属",
                        "六、参赛作品的原创性口径",
                        "八、参赛免责条款确认栏",
                    )
                )
            ),
        },
    ]

    references = [
        {
            "title": "README.md",
            "description": "安装、配置、技术栈、路线图与真实能力边界。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/README.md",
        },
        {
            "title": "docs/API.md",
            "description": "CLI 命令、参数、输出格式与退出行为。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/docs/API.md",
        },
        {
            "title": "docs/PR_WORKFLOW.md",
            "description": "Pull Request 流程、分支建议、模板和验证清单。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/docs/PR_WORKFLOW.md",
        },
        {
            "title": "docs/RELEASE.md",
            "description": "发布、分发与版本管理流程。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/docs/RELEASE.md",
        },
        {
            "title": "docs/PROJECT_DESIGN.md",
            "description": "项目设计书：架构、模块划分、数据流与关键取舍。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/docs/PROJECT_DESIGN.md",
        },
        {
            "title": "docs/INNOVATION.md",
            "description": "证据优先、混合路由、上下文降级等差异化能力。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/docs/INNOVATION.md",
        },
        {
            "title": "docs/chat-features.md",
            "description": "Chat 工作区命令、思考档位、上下文与成本说明。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/docs/chat-features.md",
        },
        {
            "title": "docs/session-and-compaction-guide.md",
            "description": "多会话切换、上下文压缩与恢复操作指南。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/docs/session-and-compaction-guide.md",
        },
        {
            "title": "docs/DEV_RECORD.md",
            "description": "2026-05-30 → 2026-09-28 的完整开发时间线与工程决策记录。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/docs/DEV_RECORD.md",
        },
        {
            "title": "CONTRIBUTING.md",
            "description": "贡献规范、协作方式与提交建议。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/CONTRIBUTING.md",
        },
        {
            "title": "THIRD_PARTY_NOTICES.md",
            "description": "第三方组件、字体、随包产物与商标声明。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/THIRD_PARTY_NOTICES.md",
        },
        {
            "title": "docs/COMPLIANCE_AND_ORIGINALITY.md",
            "description": "原创性、团队权属、AI 辅助边界、合规自检。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-Assistant/blob/main/docs/COMPLIANCE_AND_ORIGINALITY.md",
        },
    ]

    return {"tabs": tabs, "references": references}


def render_docs_data(data: dict) -> str:
    """产物全文（单行 JSON + 结尾分号）。

    落盘与防漂移守卫共用同一份序列化，守卫才能直接比对字节。
    """
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"{DATA_PREFIX}{serialized};\n"


def main() -> None:
    OUTPUT.write_text(render_docs_data(build_docs_data()), encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
