"""Rich rendering for terminal output.

The body is converted with plain links rather than wikilinks, since `[[x]]`
reads as noise in a terminal, and then handed to rich's Markdown renderer so
headings, lists, tables and blockquotes come out styled without reimplementing
any of that here.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fivet.models import Spell
from fivet.render.entries import render_blocks
from fivet.render.tags import LinkStyle, strip_tags


def _field_grid(spell: Spell) -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold cyan", justify="right", no_wrap=True)
    grid.add_column(overflow="fold")

    rows = [
        ("Casting Time", strip_tags(spell.casting_time)),
        ("Range", strip_tags(spell.range_text)),
        ("Components", strip_tags(spell.components_text)),
        ("Duration", strip_tags(spell.duration_text)),
    ]
    if spell.classes:
        rows.append(("Classes", ", ".join(spell.classes)))

    flags = []
    if spell.is_concentration:
        flags.append("concentration")
    if spell.is_ritual:
        flags.append("ritual")
    if flags:
        rows.append(("Tags", ", ".join(flags)))

    for label, value in rows:
        if value:
            grid.add_row(label, value)
    return grid


def spell_renderable(spell: Spell, data_version: str = "") -> RenderableType:
    """Build the full terminal presentation for one spell."""
    body = render_blocks(spell.entries, links=LinkStyle.PLAIN)
    higher = render_blocks(spell.entries_higher_level, links=LinkStyle.PLAIN)

    parts: list[RenderableType] = [
        Text(spell.subtitle, style="italic"),
        Text(),
        _field_grid(spell),
    ]
    if body:
        parts.extend([Text(), Markdown(body)])
    if higher:
        parts.extend([Text(), Markdown(higher)])

    footer = f"{spell.source} p.{spell.page}" if spell.page else spell.source
    if data_version:
        footer = f"{footer}  ·  5etools {data_version}"

    return Panel(
        Group(*parts),
        title=f"[bold]{spell.name}[/bold]",
        title_align="left",
        subtitle=footer,
        subtitle_align="right",
        border_style="dim",
        padding=(1, 2),
    )


def search_table(spells: list[Spell]) -> Table:
    """A compact listing for search results."""
    table = Table(box=None, pad_edge=False, header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Lvl", justify="right")
    table.add_column("School")
    table.add_column("Source")
    for spell in spells:
        table.add_row(
            spell.name,
            "C" if spell.level == 0 else str(spell.level),
            spell.school_full,
            spell.source,
        )
    return table


def source_table(counts: list[tuple[str, int]]) -> Table:
    table = Table(box=None, pad_edge=False, header_style="bold cyan")
    table.add_column("Source")
    table.add_column("Spells", justify="right")
    for source, count in counts:
        table.add_row(source, str(count))
    return table
