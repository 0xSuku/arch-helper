"""Load usage guide for the panel (basic + advanced sections)."""
from __future__ import annotations

import html
import re
from pathlib import Path

from ..device import ROOT

GUIDE_PATH = ROOT / "docs" / "GUIDE.md"
_SPLIT_MARKER = "## Advanced usage"


def _md_inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def markdown_to_html(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    in_ul = False
    in_ol = False
    in_pre = False
    in_table = False
    table_rows: list[str] = []

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    def flush_table() -> None:
        nonlocal in_table, table_rows
        if not in_table:
            return
        if table_rows:
            out.append('<table class="guide-table">')
            for i, row in enumerate(table_rows):
                cells = [c.strip() for c in row.strip("|").split("|")]
                tag = "th" if i == 0 else "td"
                out.append("<tr>" + "".join(f"<{tag}>{_md_inline(c)}</{tag}>" for c in cells) + "</tr>")
            out.append("</table>")
        table_rows = []
        in_table = False

    for raw in lines:
        line = raw.rstrip()

        if line.startswith("```"):
            if in_pre:
                out.append("</pre>")
                in_pre = False
            else:
                close_lists()
                flush_table()
                out.append('<pre class="guide-code">')
                in_pre = True
            continue

        if in_pre:
            out.append(html.escape(line))
            continue

        if line.startswith("|") and "|" in line[1:]:
            close_lists()
            if not in_table:
                in_table = True
                table_rows = []
            if re.match(r"^\|[-:\s|]+\|$", line):
                continue
            table_rows.append(line)
            continue

        flush_table()

        if not line.strip():
            close_lists()
            continue

        if line.startswith("### "):
            close_lists()
            out.append(f"<h4>{_md_inline(line[4:])}</h4>")
            continue
        if line.startswith("## "):
            close_lists()
            out.append(f"<h3>{_md_inline(line[3:])}</h3>")
            continue
        if line.startswith("# "):
            close_lists()
            out.append(f"<h2>{_md_inline(line[2:])}</h2>")
            continue

        m = re.match(r"^(\d+)\.\s+(.*)", line)
        if m:
            if not in_ol:
                close_lists()
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_md_inline(m.group(2))}</li>")
            continue

        if line.startswith("- "):
            if not in_ul:
                close_lists()
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_md_inline(line[2:])}</li>")
            continue

        close_lists()
        out.append(f"<p>{_md_inline(line)}</p>")

    if in_pre:
        out.append("</pre>")
    close_lists()
    flush_table()
    return "\n".join(out)


def load_guide_sections() -> dict[str, str]:
    if not GUIDE_PATH.exists():
        return {
            "basic_html": "<p>Guide file missing: docs/GUIDE.md</p>",
            "advanced_html": "",
        }
    text = GUIDE_PATH.read_text(encoding="utf-8")
    if _SPLIT_MARKER in text:
        basic_md, advanced_md = text.split(_SPLIT_MARKER, 1)
        basic_md = basic_md.strip()
        advanced_md = (_SPLIT_MARKER + advanced_md).strip()
    else:
        basic_md = text.strip()
        advanced_md = ""
    return {
        "basic_html": markdown_to_html(basic_md),
        "advanced_html": markdown_to_html(advanced_md),
    }
