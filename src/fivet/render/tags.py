"""Conversion of 5etools ``{@tag}`` markup into markdown or plain text.

The tag semantics here are taken from upstream's `Renderer.tag` classes and
their ``_getStripped`` methods, not reinvented. Where this module deviates it is
to produce markdown rather than HTML, and each deviation is commented.

Tags nest: upstream's splitters are depth aware, and spell text contains at
least one genuinely nested tag, so the tokenizer here is depth aware too.
"""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import quote

MAX_DEPTH = 8
"""Recursion guard. Observed nesting depth in spell data is 2."""


class LinkStyle(StrEnum):
    """How cross-reference tags render."""

    WIKILINK = "wikilink"
    PLAIN = "plain"
    URL = "url"


SITE_ROOT = "https://5e.tools"

# Tags whose referent has a stable 5e.tools page, for LinkStyle.URL.
_URL_PAGES = {
    "action": "actions.html",
    "background": "backgrounds.html",
    "condition": "conditionsdiseases.html",
    "creature": "bestiary.html",
    "deity": "deities.html",
    "disease": "conditionsdiseases.html",
    "feat": "feats.html",
    "hazard": "trapshazards.html",
    "item": "items.html",
    "language": "languages.html",
    "object": "objects.html",
    "optfeature": "optionalfeatures.html",
    "psionic": "psionics.html",
    "race": "races.html",
    "reward": "rewards.html",
    "spell": "spells.html",
    "status": "conditionsdiseases.html",
    "trap": "trapshazards.html",
    "variantrule": "variantrules.html",
    "vehicle": "vehicles.html",
}

# Cross-reference tags: name|source|displayText, display text at index 2.
_REFERENCE_TAGS = frozenset(
    {
        "action",
        "background",
        "boon",
        "card",
        "charoption",
        "classFeature",
        "condition",
        "creature",
        "cult",
        "deck",
        "deity",
        "disease",
        "facility",
        "feat",
        "hazard",
        "item",
        "itemMastery",
        "itemProperty",
        "language",
        "legroup",
        "object",
        "optfeature",
        "psionic",
        "race",
        "recipe",
        "reward",
        "sense",
        "skill",
        "spell",
        "status",
        "subclass",
        "subclassFeature",
        "table",
        "trap",
        "variantrule",
        "vehicle",
        "vehupgrade",
    }
)

# Tags that wrap their content in markdown emphasis. Content is rendered first.
_STYLE_TAGS = {
    "b": "**",
    "bold": "**",
    "i": "*",
    "italic": "*",
    "note": "*",
    "s": "~~",
    "strike": "~~",
    "code": "`",
}

# Tags whose first argument is already the human-readable text.
_FIRST_ARG_TAGS = frozenset(
    {
        "adventure",
        "book",
        "filter",
        "footnote",
        "highlight",
        "homebrew",
        "link",
        "u",
        "underline",
        "color",
        "font",
        "help",
        "kbd",
        "style",
        "sub",
        "sup",
        "tip",
        "comic",
        "comicNote",
        "area",
        "cite",
    }
)

_DICE_TAGS = frozenset({"dice", "autodice", "damage"})
_D20_TAGS = frozenset({"d20", "hit", "initiative"})
_SCALING_TAGS = frozenset({"scaledice", "scaledamage"})

_PROMPT_NUMBER = re.compile(r"#\$prompt_number[^$]*\$#")
_TRAILING_QUALIFIER = re.compile(r"\s*\[[^\]]*\]\s*$")

# encodeURIComponent leaves these unescaped; upstream lowercases the result.
_HASH_SAFE = "-_.!~*'()"


def split_by_tags(text: str) -> list[str]:
    """Split a string into literal and whole-tag segments, depth aware.

    Mirrors upstream's `Renderer.splitByTags`: a `{` only opens a tag when
    followed by `@`, and nested tags stay inside their parent segment.
    """
    out: list[str] = []
    current = ""
    depth = 0
    i = 0
    length = len(text)
    while i < length:
        char = text[i]
        nxt = text[i + 1] if i + 1 < length else ""
        if char == "{":
            if nxt != "@":
                current += "{"
            elif depth > 0:
                depth += 1
                current += "{"
            else:
                depth += 1
                if current:
                    out.append(current)
                current = "{@"
                i += 1
        elif char == "}":
            current += "}"
            if depth != 0:
                depth -= 1
                if depth == 0:
                    out.append(current)
                    current = ""
        else:
            current += char
        i += 1
    if current:
        out.append(current)
    return out


def split_tag_by_pipe(text: str) -> list[str]:
    """Split a tag body on unescaped, untagged pipes.

    Mirrors upstream's `_splitByPipeBase`: a pipe inside a nested tag belongs to
    that tag, and a backslash-escaped pipe is literal.
    """
    out: list[str] = []
    current = ""
    depth = 0
    for i, char in enumerate(text):
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if char == "{":
            if nxt == "@":
                depth += 1
            current += "{"
        elif char == "}":
            if depth:
                depth -= 1
            current += "}"
        elif char == "|":
            if prev == "\\":
                current += char
            elif depth:
                current += "|"
            else:
                out.append(current)
                current = ""
        else:
            current += char
    if current:
        out.append(current)
    return out


def _hash_part(value: str) -> str:
    """Encode one hash component the way upstream's `toUrlified` does."""
    return quote(value.lower(), safe=_HASH_SAFE).lower()


def _url_for(tag: str, name: str, source: str) -> str | None:
    """Build a 5e.tools URL, or None when no reliable link can be made."""
    page = _URL_PAGES.get(tag)
    if not page or not source:
        return None
    return f"{SITE_ROOT}/{page}#{_hash_part(name)}_{_hash_part(source)}"


def _strip_qualifier(name: str) -> str:
    """Drop a trailing bracketed qualifier: "Sphere [Area of Effect]" to "Sphere".

    Upstream keeps the qualifier when a tag supplies no display text. No such
    case exists in current spell data, so this only guards future additions.
    """
    return _TRAILING_QUALIFIER.sub("", name)


def _render_reference(tag: str, parts: list[str], links: LinkStyle) -> str:
    name = parts[0] if parts else ""
    source = parts[1] if len(parts) > 1 else ""
    display = parts[2] if len(parts) > 2 and parts[2] else _strip_qualifier(name)
    target = _strip_qualifier(name)

    if links is LinkStyle.PLAIN:
        return display
    if links is LinkStyle.URL:
        url = _url_for(tag, target, source)
        return f"[{display}]({url})" if url else display
    # Wikilink. Use the piped form when the display text diverges from the note
    # name, so the link still resolves to a canonically named note.
    if display != target:
        return f"[[{target}|{display}]]"
    return f"[[{target}]]"


def _render_dice(parts: list[str]) -> str:
    roll = parts[0] if parts else ""
    display = parts[1] if len(parts) > 1 and parts[1] else ""
    text = display or roll.replace(";", "/")
    # The italic n is upstream's own placeholder glyph for a prompted number.
    return _PROMPT_NUMBER.sub("(𝑛)", text)  # noqa: RUF001


def _render_d20(parts: list[str]) -> str:
    roll = parts[0] if parts else ""
    display = parts[1] if len(parts) > 1 and parts[1] else ""
    if display:
        return display
    try:
        number = int(roll)
    except ValueError:
        return roll
    return f"+{number}" if number >= 0 else str(number)


def _render_tag(tag: str, body: str, links: LinkStyle, depth: int) -> str:
    parts = split_tag_by_pipe(body)
    first = parts[0] if parts else ""

    if tag in _STYLE_TAGS:
        marker = _STYLE_TAGS[tag]
        inner = render(first, links=links, _depth=depth + 1)
        return f"{marker}{inner}{marker}" if inner else ""

    if tag in _DICE_TAGS:
        return _render_dice(parts)

    if tag in _D20_TAGS:
        return _render_d20(parts)

    if tag in _SCALING_TAGS:
        # base|levelRange|step|_|displayText. Upstream shows the step, because
        # the sentence around it reads "increases by X for each slot level".
        display = parts[4] if len(parts) > 4 and parts[4] else ""
        return display or (parts[2] if len(parts) > 2 else first)

    if tag == "dc":
        display = parts[1] if len(parts) > 1 and parts[1] else first
        return f"DC {display}"

    if tag == "dcYourSpellSave":
        return first or "your spell save DC"

    if tag == "hitYourSpellAttack":
        return first or "your spell attack modifier"

    if tag == "chance":
        display = parts[1] if len(parts) > 1 and parts[1] else ""
        return display or f"{first} percent"

    if tag == "recharge":
        try:
            value = int(first) if first else 6
        except ValueError:
            return "(Recharge ?)"
        suffix = "\u20136" if value < 6 else ""  # upstream uses an en dash for the range
        return f"(Recharge {value}{suffix})"

    if tag == "quickref":
        # name|source|ixChapter|ixHeader|displayText
        display = parts[4] if len(parts) > 4 and parts[4] else ""
        return display or first

    if tag in _REFERENCE_TAGS:
        return _render_reference(tag, parts, links)

    if tag in _FIRST_ARG_TAGS:
        return first

    # Unknown tag. Degrade to the first argument: an unrecognized tag should
    # read as prose, never leak literal markup into someone's notes.
    return first


def render(
    text: str,
    links: LinkStyle = LinkStyle.WIKILINK,
    _depth: int = 0,
) -> str:
    """Convert a 5etools markup string into markdown."""
    if not text:
        return text
    if _depth > MAX_DEPTH:
        return text
    out = []
    for segment in split_by_tags(text):
        if not segment.startswith("{@"):
            out.append(segment)
            continue
        inner = segment[1:-1] if segment.endswith("}") else segment[1:]
        tag, _, body = inner.partition(" ")
        tag = tag.lstrip("@")
        out.append(_render_tag(tag, body, links, _depth))
    return "".join(out)


def strip_tags(text: str) -> str:
    """Convert markup to plain text with no markdown syntax."""
    return render(text, links=LinkStyle.PLAIN)
