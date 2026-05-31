from __future__ import annotations

import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
API_DOC = ROOT / "docs" / "API.md"
WORKFLOW_DOC = ROOT / "docs" / "PR_WORKFLOW.md"
OUTPUT = ROOT / "website" / "assets" / "docs-data.js"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def extract_section(markdown: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(markdown)
    if not match:
        raise ValueError(f"Section not found: {heading}")
    return match.group("body").strip()


def extract_between(markdown: str, start_heading: str, end_heading: str | None = None) -> str:
    start_token = f"## {start_heading}\n"
    start_index = markdown.find(start_token)
    if start_index == -1:
        raise ValueError(f"Section start not found: {start_heading}")

    body_start = start_index + len(start_token)
    if end_heading is None:
        return markdown[body_start:].strip()

    end_token = f"## {end_heading}\n"
    end_index = markdown.find(end_token, body_start)
    if end_index == -1:
        raise ValueError(f"Section end not found: {end_heading}")
    return markdown[body_start:end_index].strip()


def inline_format(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


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

        if stripped.startswith("### "):
            parts.append(f"<h4>{inline_format(stripped[4:])}</h4>")
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
            parts.append("<ol>" + "".join(f"<li>{inline_format(item)}</li>" for item in items) + "</ol>")
            continue

        if stripped.startswith("- "):
            items: list[str] = []
            while i < len(lines):
                current = lines[i].strip()
                if not current.startswith("- "):
                    break
                items.append(current[2:])
                i += 1
            parts.append("<ul>" + "".join(f"<li>{inline_format(item)}</li>" for item in items) + "</ul>")
            continue

        paragraph_lines = [stripped]
        i += 1
        while i < len(lines):
            current = lines[i].strip()
            if not current or current.startswith(("```", "### ", "- ")) or re.match(r"^\d+\.\s+", current):
                break
            paragraph_lines.append(current)
            i += 1
        parts.append(f"<p>{inline_format(' '.join(paragraph_lines))}</p>")

    return "\n".join(parts)


def build_docs_data() -> dict:
    readme = read_text(README)
    api_doc = read_text(API_DOC)
    workflow_doc = read_text(WORKFLOW_DOC)

    tabs = [
        {
            "id": "quickstart",
            "label": "快速开始",
            "title": "README · 快速开始",
            "source": "README.md",
            "html": markdown_to_html(extract_section(readme, "快速开始")),
        },
        {
            "id": "config-priority",
            "label": "配置优先级",
            "title": "README · 配置优先级",
            "source": "README.md",
            "html": markdown_to_html(extract_between(readme, "配置优先级", "必需环境变量")),
        },
        {
            "id": "env",
            "label": "环境变量",
            "title": "README · 必需环境变量",
            "source": "README.md",
            "html": markdown_to_html(extract_between(readme, "必需环境变量", "配置模型供应商")),
        },
        {
            "id": "provider-config",
            "label": "Provider 配置",
            "title": "README · 配置模型供应商",
            "source": "README.md",
            "html": markdown_to_html(extract_between(readme, "配置模型供应商", "使用")),
        },
        {
            "id": "usage",
            "label": "使用示例",
            "title": "README · 使用",
            "source": "README.md",
            "html": markdown_to_html(extract_between(readme, "使用", "CLI 命令")),
        },
        {
            "id": "cli-api",
            "label": "CLI API",
            "title": "API 文档 · 主命令与配置命令",
            "source": "docs/API.md",
            "html": markdown_to_html(
                extract_section(api_doc, "主命令") + "\n\n" + extract_section(api_doc, "配置命令")
            ),
        },
        {
            "id": "project-structure",
            "label": "项目结构",
            "title": "README · 代码结构",
            "source": "README.md",
            "html": markdown_to_html(extract_between(readme, "代码结构", "测试与质量检查")),
        },
        {
            "id": "workflow-guide",
            "label": "PR 工作流",
            "title": "PR Workflow Guide",
            "source": "docs/PR_WORKFLOW.md",
            "html": markdown_to_html(workflow_doc),
        },
    ]

    references = [
        {
            "title": "README.md",
            "description": "安装、配置、技术栈、路线图与真实能力边界。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-/blob/main/README.md",
        },
        {
            "title": "docs/API.md",
            "description": "CLI 命令、参数、输出格式与退出行为。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-/blob/main/docs/API.md",
        },
        {
            "title": "docs/PR_WORKFLOW.md",
            "description": "Pull Request 流程、分支建议、模板和验证清单。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-/blob/main/docs/PR_WORKFLOW.md",
        },
        {
            "title": "docs/RELEASE.md",
            "description": "发布、分发与版本管理流程。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-/blob/main/docs/RELEASE.md",
        },
        {
            "title": "CONTRIBUTING.md",
            "description": "贡献规范、协作方式与提交建议。",
            "url": "https://github.com/JiangLai999/AI-PR-Review-/blob/main/CONTRIBUTING.md",
        },
    ]

    return {"tabs": tabs, "references": references}


def main() -> None:
    data = build_docs_data()
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUTPUT.write_text(f"window.__WEBSITE_DOCS__ = {serialized};\n", encoding="utf-8")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
