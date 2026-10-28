"""Conversion of the 5etools recursive `entries` tree into markdown blocks.

Spell data uses six entry types (docs/DESIGN.md section 6.2): strings, `entries`,
`list`, `item`, `table` and `inset`. In spell data every `entries` block sits at
nesting depth 0, but the structure is recursive by design and the bestiary nests
deeply, so this renderer handles arbitrary depth.

Output is a list of markdown blocks, joined with blank lines by `render_blocks`.
"""

from __future__ import annotations

from typing import Any

from fivet.render.tags import LinkStyle
from fivet.render.tags import render as render_markup

MAX_HEADING_LEVEL = 6
"""Past h6 there is no deeper ATX heading, so named entries become lead-ins."""

# Upstream's sentinel for an open-ended table row bound.
_POS_INFINITE = 100_000_000


def _text(value: Any, links: LinkStyle) -> str:
    """Render a leaf value to inline markdown."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return render_markup(value, links=links)


def _indent(block: str, prefix: str = "  ") -> str:
    """Indent every line after the first, for continuation under a list bullet."""
    lines = block.split("\n")
    return "\n".join([lines[0]] + [f"{prefix}{line}" if line else "" for line in lines[1:]])


def _cell_to_text(cell: Any, links: LinkStyle) -> str:
    """Render one table cell, including upstream's rollable `cell` objects."""
    if not isinstance(cell, dict):
        return _text(cell, links)

    if cell.get("type") != "cell":
        return " ".join(render_blocks(cell.get("entries", []), links=links).split("\n\n"))

    roll = cell.get("roll")
    if not roll:
        return _text(cell.get("entry"), links)

    if roll.get("exact") is not None:
        exact = roll["exact"]
        return f"{exact:02d}" if roll.get("pad") else str(exact)

    low = roll.get("displayMin", roll.get("min"))
    high = roll.get("displayMax", roll.get("max"))
    if roll.get("pad"):
        low_text = f"{low:02d}" if low is not None else ""
        high_text = f"{high:02d}" if high is not None else ""
    else:
        low_text = "" if low is None else str(low)
        high_text = "" if high is None else str(high)

    # An open-ended bound renders as "20 or lower" / "99 or higher", matching
    # how upstream presents its infinite sentinel.
    if low is not None and low <= -_POS_INFINITE:
        return f"{high_text} or lower"
    if high is not None and high >= _POS_INFINITE:
        return f"{low_text} or higher"
    if low_text == high_text:
        return low_text
    return f"{low_text}-{high_text}"


def _render_table(entry: dict[str, Any], links: LinkStyle) -> list[str]:
    blocks: list[str] = []

    caption = entry.get("caption")
    if caption:
        # GFM has no table caption, so it becomes a bold line above the table.
        blocks.append(f"**{_text(caption, links)}**")

    col_labels = [_text(label, links) for label in entry.get("colLabels") or []]
    rows = entry.get("rows") or []

    if not col_labels and rows:
        # A table with no labels still needs a header row to be valid GFM.
        width = max(len(row) for row in rows if isinstance(row, list))
        col_labels = [""] * width

    lines = [
        "| " + " | ".join(col_labels) + " |",
        "| " + " | ".join("---" for _ in col_labels) + " |",
    ]
    for row in rows:
        cells = row.get("row", []) if isinstance(row, dict) else row
        rendered = [_cell_to_text(cell, links).replace("|", r"\|") for cell in cells]
        # Pad short rows so the table stays well formed.
        rendered += [""] * (len(col_labels) - len(rendered))
        lines.append("| " + " | ".join(rendered) + " |")

    blocks.append("\n".join(lines))
    return blocks


def _render_list(entry: dict[str, Any], links: LinkStyle, depth: int) -> list[str]:
    bullets = []
    for item in entry.get("items") or []:
        rendered = _render_list_item(item, links, depth)
        if rendered:
            bullets.append(_indent(f"- {rendered}"))
    return ["\n".join(bullets)] if bullets else []


def _render_list_item(item: Any, links: LinkStyle, depth: int) -> str:
    if isinstance(item, str):
        return _text(item, links)
    if not isinstance(item, dict):
        return _text(item, links)

    name = item.get("name")
    body_entries = item.get("entries")
    if body_entries is None and item.get("entry") is not None:
        body_entries = [item["entry"]]

    body = render_blocks(body_entries or [], links=links, depth=depth + 1)
    if name:
        # Upstream's hanging list style puts the name inline with the text.
        lead = f"**{_text(name, links)}.**"
        return f"{lead} {body}".strip()
    return body


def _render_inset(entry: dict[str, Any], links: LinkStyle, depth: int) -> list[str]:
    inner = render_blocks(entry.get("entries") or [], links=links, depth=depth + 1)
    name = entry.get("name")
    lines = []
    if name:
        lines.append(f"**{_text(name, links)}**")
        lines.append("")
    lines.extend(inner.split("\n"))
    quoted = "\n".join(f"> {line}".rstrip() for line in lines)
    return [quoted] if inner or name else []


def _render_quote(entry: dict[str, Any], links: LinkStyle, depth: int) -> list[str]:
    inner = render_blocks(entry.get("entries") or [], links=links, depth=depth + 1)
    lines = [f"> {line}".rstrip() for line in inner.split("\n")]
    by = entry.get("by")
    if by:
        lines.append(">")
        lines.append(f"> {chr(0x2014)} {_text(by, links)}")
    return ["\n".join(lines)] if inner else []


def _render_entries(
    entry: dict[str, Any], links: LinkStyle, depth: int, base_level: int
) -> list[str]:
    blocks: list[str] = []
    name = entry.get("name")
    level = base_level + depth

    if name:
        rendered_name = _text(name, links)
        if level <= MAX_HEADING_LEVEL:
            blocks.append(f"{'#' * level} {rendered_name}")
            name_lead = None
        else:
            name_lead = f"**{rendered_name}.**"
    else:
        name_lead = None

    inner = _render_any(
        entry.get("entries") or [], links=links, depth=depth + 1, base_level=base_level
    )
    if name_lead and inner:
        inner[0] = f"{name_lead} {inner[0]}"
    elif name_lead:
        inner = [name_lead]
    blocks.extend(inner)
    return blocks


def _render_entry(entry: Any, links: LinkStyle, depth: int, base_level: int) -> list[str]:
    if entry is None:
        return []
    if isinstance(entry, str | int | float):
        text = _text(entry, links)
        return [text] if text else []
    if not isinstance(entry, dict):
        return []

    entry_type = entry.get("type", "entries")

    if entry_type in ("entries", "section", "variant", "variantSub"):
        return _render_entries(entry, links, depth, base_level)
    if entry_type == "list":
        return _render_list(entry, links, depth)
    if entry_type == "item":
        rendered = _render_list_item(entry, links, depth)
        return [rendered] if rendered else []
    if entry_type == "table":
        return _render_table(entry, links)
    if entry_type in ("inset", "insetReadaloud"):
        return _render_inset(entry, links, depth)
    if entry_type == "quote":
        return _render_quote(entry, links, depth)

    # Unknown container: recurse into whatever children it has rather than
    # dropping content on the floor.
    if entry.get("entries") is not None:
        return _render_any(entry["entries"], links=links, depth=depth, base_level=base_level)
    if entry.get("entry") is not None:
        return _render_entry(entry["entry"], links, depth, base_level)
    return []


def _render_any(entries: Any, links: LinkStyle, depth: int, base_level: int) -> list[str]:
    if not isinstance(entries, list):
        entries = [entries]
    blocks: list[str] = []
    for entry in entries:
        blocks.extend(_render_entry(entry, links, depth, base_level))
    return blocks


def render_block_list(
    entries: Any,
    links: LinkStyle = LinkStyle.WIKILINK,
    depth: int = 0,
    base_level: int = 2,
) -> list[str]:
    """Render an entries tree to a list of markdown blocks."""
    return _render_any(entries, links=links, depth=depth, base_level=base_level)


def render_blocks(
    entries: Any,
    links: LinkStyle = LinkStyle.WIKILINK,
    depth: int = 0,
    base_level: int = 2,
) -> str:
    """Render an entries tree to markdown, blocks separated by blank lines."""
    return "\n\n".join(render_block_list(entries, links=links, depth=depth, base_level=base_level))
