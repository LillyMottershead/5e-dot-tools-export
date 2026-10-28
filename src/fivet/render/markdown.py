"""Markdown export through Jinja2 templates.

Per docs/DESIGN.md section 10, templates receive a flat context whose values
are already rendered, so writing a template needs no knowledge of the 5etools
schema. Templates do layout, never parsing.

Frontmatter values are plain text with markup stripped, while body prose uses
the configured link style. A wikilink is not useful as an Obsidian property
value, and a value beginning with `[` would be parsed as a YAML flow sequence
and corrupt the frontmatter, so the `yaml` filter quotes whatever needs it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from fivet import config
from fivet.models import Spell
from fivet.render.entries import MAX_HEADING_LEVEL, render_blocks
from fivet.render.tags import LinkStyle, strip_tags

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
TEMPLATE_SUFFIX = ".md.j2"

DEFAULT_TEMPLATE = "obsidian"

# Scalars YAML would otherwise reinterpret as a bool, null or number.
_YAML_KEYWORDS = {
    "true",
    "false",
    "yes",
    "no",
    "on",
    "off",
    "null",
    "none",
    "~",
    "y",
    "n",
}
# Characters that carry meaning at the start of a YAML scalar.
_YAML_LEADING = set("-?:,[]{}#&*!|>'\"%@`")
_NUMERIC = re.compile(r"^[-+]?(\d[\d_]*\.?[\d_]*|\.\d[\d_]*)([eE][-+]?\d+)?$")
# Inside a flow sequence these separate items rather than being ordinary text.
_YAML_FLOW_INDICATORS = ",[]{}"


class TemplateMissingError(RuntimeError):
    """Raised when a named template exists in neither the user nor shipped dir."""


def yaml_scalar(value: Any, in_flow: bool = False) -> str:
    """Render a value as a YAML scalar, quoting it only when necessary.

    `in_flow` tightens the rules for an item inside a flow sequence, where a
    comma or bracket separates items rather than being ordinary text.
    """
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)

    text = str(value)
    needs_quotes = (
        not text
        or text[0] in _YAML_LEADING
        or text[0].isspace()
        or text[-1].isspace()
        or ": " in text
        or text.endswith(":")
        or " #" in text
        or "\n" in text
        or text.strip().lower() in _YAML_KEYWORDS
        or bool(_NUMERIC.match(text))
        or (in_flow and any(char in text for char in _YAML_FLOW_INDICATORS))
    )
    if not needs_quotes:
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def yaml_flow_list(values: Any) -> str:
    """Render a list as a YAML flow sequence with each item safely quoted."""
    if not values:
        return "[]"
    return "[" + ", ".join(yaml_scalar(value, in_flow=True) for value in values) + "]"


def _slug(text: str) -> str:
    """A lowercase, hyphenated token suitable for an Obsidian tag."""
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def build_context(
    spell: Spell,
    links: LinkStyle = LinkStyle.WIKILINK,
    data_version: str = "",
) -> dict[str, Any]:
    """Assemble the flat template context.

    Everything is pre-rendered here. Frontmatter-bound values are plain text;
    `description_md` and `higher_levels_md` carry the configured link style.
    """
    tags = [f"spell/level/{spell.level}"]
    if spell.school_full:
        tags.append(f"spell/school/{_slug(spell.school_full)}")
    if spell.is_concentration:
        tags.append("spell/concentration")
    if spell.is_ritual:
        tags.append("spell/ritual")

    source_page = f"{spell.source} p.{spell.page}" if spell.page else spell.source

    return {
        "name": spell.name,
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
        "source": spell.source,
        "page": spell.page,
        "source_page": source_page,
        "uid": spell.uid,
        "tags": tags,
        "damage_types": spell.damage_inflict,
        "saving_throws": spell.saving_throw,
        "conditions": spell.condition_inflict,
        "description_md": render_blocks(spell.entries, links=links),
        "higher_levels_md": render_blocks(spell.entries_higher_level, links=links),
        # The same content with its heading folded into a bold lead-in, for
        # templates where an h2 would be out of place.
        "higher_levels_inline": render_blocks(
            spell.entries_higher_level, links=links, base_level=MAX_HEADING_LEVEL + 1
        ),
        "data_version": data_version,
    }


def _environment(extra_dirs: list[Path] | None = None) -> Environment:
    """Jinja environment searching user overrides before shipped templates."""
    search = [*(extra_dirs or []), config.template_dir(), TEMPLATE_DIR]
    env = Environment(
        loader=FileSystemLoader([str(path) for path in search]),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,
    )
    env.filters["yaml"] = yaml_scalar
    env.filters["yaml_list"] = yaml_flow_list
    env.filters["slug"] = _slug
    return env


def available_templates(extra_dirs: list[Path] | None = None) -> list[str]:
    """Template names found in the user dir and the shipped dir, deduplicated."""
    names: list[str] = []
    for directory in [*(extra_dirs or []), config.template_dir(), TEMPLATE_DIR]:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(f"*{TEMPLATE_SUFFIX}")):
            name = path.name[: -len(TEMPLATE_SUFFIX)]
            if name not in names:
                names.append(name)
    return names


def render_spell(
    spell: Spell,
    template: str = DEFAULT_TEMPLATE,
    links: LinkStyle = LinkStyle.WIKILINK,
    data_version: str = "",
    extra_dirs: list[Path] | None = None,
) -> str:
    """Render one spell to markdown using the named template."""
    env = _environment(extra_dirs)
    try:
        loaded = env.get_template(f"{template}{TEMPLATE_SUFFIX}")
    except TemplateNotFound as exc:
        known = ", ".join(available_templates(extra_dirs)) or "none"
        raise TemplateMissingError(f"No template named {template!r}. Available: {known}.") from exc

    context = build_context(spell, links=links, data_version=data_version)
    rendered = loaded.render(**context)
    # Collapse runs of blank lines a conditional block may have left behind.
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return rendered.strip() + "\n"
