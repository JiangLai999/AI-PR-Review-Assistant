"""Shared pixel-console visual primitives and bilingual labels."""

from __future__ import annotations

from typing import Any

from rich.text import Text

PIXEL_BRAND = [
    "██████  ██████      ██████  ███████ ██    ██ ██ ███████ ██  ██",
    "██   ██ ██   ██     ██   ██ ██      ██    ██ ██ ██      ██  ██",
    "██████  ██████      ██████  █████   ██    ██ ██ █████   ██████",
    "██      ██   ██     ██   ██ ██       ██  ██  ██ ██      ██  ██",
    "██      ██   ██     ██   ██ ███████   ████   ██ ███████ ██  ██",
]


def is_english(language: str | None) -> bool:
    return str(language or "zh-CN").lower().startswith("en")


def tr(language: str | None, zh: str, en: str) -> str:
    return en if is_english(language) else zh


def runtime_mode(config: Any) -> str:
    provider = str(getattr(config.provider, "name", "")).lower()
    strategy = str(getattr(getattr(config, "preferences", None), "hybrid_strategy", ""))
    if provider in {"ollama", "local"} or strategy == "local_only":
        return "LOCAL"
    if strategy in {"quality_first", "remote_only"}:
        return "REMOTE"
    return "HYBRID"


def runtime_mode_label(config: Any, language: str | None) -> str:
    mode = runtime_mode(config)
    labels = {
        "LOCAL": tr(language, "本地运行", "LOCAL RUNTIME"),
        "REMOTE": tr(language, "远程运行", "REMOTE RUNTIME"),
        "HYBRID": tr(language, "混合运行", "HYBRID RUNTIME"),
    }
    return labels[mode]


def pixel_brand(style: str = "bold white") -> Text:
    text = Text()
    for line in PIXEL_BRAND:
        text.append(line + "\n", style=style)
    return text


def _cell_len(value: str) -> int:
    return Text(value).cell_len


def _pixel_line(value: str, width: int) -> str:
    value = str(value)
    # One border cell + two left spaces + content + two right spaces + one
    # border cell. Padding is based on terminal cells, not Python characters.
    available = max(0, width - 6)
    if _cell_len(value) > available:
        value = value[: max(0, available - 1)] + "…"
    return f"║  {value}{' ' * max(0, available - _cell_len(value))}  ║"


def pixel_frame(
    title: str,
    lines: list[str],
    *,
    subtitle: str | None = None,
    width: int = 76,
    border_style: str = "cyan",
) -> Text:
    """Render a fixed-grid 8-bit frame using one consistent border language."""
    width = max(48, width)
    inner = width - 2
    output = Text()
    output.append("╔" + "═" * inner + "╗\n", style=f"bold {border_style}")
    title_line = f"║  {title}"
    title_line += " " * max(0, width - 4 - _cell_len(title)) + "║"
    output.append(title_line + "\n", style=f"bold {border_style}")
    output.append("╠" + "═" * inner + "╣\n", style=border_style)
    for line in lines:
        output.append(_pixel_line(line, width) + "\n", style="white")
    if subtitle:
        output.append("╟" + "─" * inner + "╢\n", style="dim")
        output.append(_pixel_line(subtitle, width) + "\n", style="grey62")
    output.append("╚" + "═" * inner + "╝", style=f"bold {border_style}")
    return output


def pixel_print_frame(console: Any, title: str, lines: list[str], **kwargs: Any) -> None:
    console.print(pixel_frame(title, lines, **kwargs))


def pixel_header(title: str, subtitle: str, *, language: str | None = None) -> Text:
    lines = [
        *PIXEL_BRAND,
        "",
        title,
        subtitle,
    ]
    return pixel_frame(
        "AI PR REVIEW // PIXEL TERMINAL", lines, width=92, border_style="bright_cyan"
    )


def pixel_step_header(
    console: Any,
    *,
    step: int,
    total: int,
    title_zh: str,
    title_en: str,
    detail_zh: str,
    detail_en: str,
    language: str | None = None,
) -> None:
    title = tr(language, title_zh, title_en)
    detail = tr(language, detail_zh, detail_en)
    progress = "█" * step + "░" * max(0, total - step)
    pixel_print_frame(
        console,
        f"{step:02d}/{total:02d}  {title}",
        [f"PROGRESS  {progress}", detail],
        subtitle=tr(language, "像素配置控制台", "PIXEL CONFIG CONSOLE"),
        width=92,
        border_style="bright_cyan",
    )


def pixel_menu(
    console: Any,
    *,
    title: str,
    rows: list[str],
    subtitle: str | None = None,
    width: int = 92,
    border_style: str = "cyan",
) -> None:
    pixel_print_frame(
        console, title, rows, subtitle=subtitle, width=width, border_style=border_style
    )


def pixel_status_table(rows: list[tuple[str, str, str]], *, title: str) -> Text:
    rendered = [f"{status}  {item:<24} {value}" for status, item, value in rows]
    return pixel_frame(title, rendered, width=92, border_style="green")
