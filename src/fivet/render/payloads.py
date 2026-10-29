"""JSON payloads for `--format json`.

Per docs/DESIGN.md section 8.1 the JSON a command emits is its normalized
display view, not the raw upstream record: the same values the templates and
the terminal panel are built from, under the field names the rest of this tool
uses. The raw record stays an implementation detail of the cache, so an
upstream schema change cannot silently reshape a consumer's input.

Every payload is a JSON object rather than a bare array, so a later version can
add a key without breaking anything that reads one.
"""

from __future__ import annotations

from typing import Any

from fivet.models import Spell
from fivet.render.entries import render_blocks
from fivet.render.tags import LinkStyle, strip_tags


def spell_row(spell: Spell) -> dict[str, Any]:
    """The listing view: the columns the search table and the TSV lines carry."""
    return {
        "name": spell.name,
        "source": spell.source,
        "level": spell.level,
        "level_text": spell.level_text,
        "school": spell.school_full,
    }


def spell_payload(
    spell: Spell,
    links: LinkStyle = LinkStyle.PLAIN,
    data_version: str = "",
) -> dict[str, Any]:
    """The full display view of one spell.

    Scalar fields are plain text, as in frontmatter. `description` and
    `higher_levels` are markdown prose carrying the requested link style, since
    the entries tree has no faithful representation that is not prose.
    """
    return {
        "name": spell.name,
        "source": spell.source,
        "page": spell.page,
        "level": spell.level,
        "level_text": spell.level_text,
        "school": spell.school_full,
        "subtitle": spell.subtitle,
        "casting_time": strip_tags(spell.casting_time),
        "range": strip_tags(spell.range_text),
        "components": strip_tags(spell.components_text),
        "duration": strip_tags(spell.duration_text),
        "concentration": spell.is_concentration,
        "ritual": spell.is_ritual,
        "classes": spell.classes,
        "damage_types": spell.damage_inflict,
        "saving_throws": spell.saving_throw,
        "conditions": spell.condition_inflict,
        "description": render_blocks(spell.entries, links=links),
        "higher_levels": render_blocks(spell.entries_higher_level, links=links),
        "uid": spell.uid,
        "data_version": data_version,
    }


def search_payload(spells: list[Spell], data_version: str = "") -> dict[str, Any]:
    """A result listing, including the empty one: no match is not an error."""
    return {
        "count": len(spells),
        "results": [spell_row(spell) for spell in spells],
        "data_version": data_version,
    }


def sources_payload(counts: list[tuple[str, int]], data_version: str = "") -> dict[str, Any]:
    return {
        "sources": [{"source": source, "spells": count} for source, count in counts],
        "data_version": data_version,
    }
