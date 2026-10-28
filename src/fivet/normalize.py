"""Normalization of 5etools spell metadata into display strings.

Every mapping here is a closed enumeration confirmed against the upstream data
(see docs/DESIGN.md section 3.2). The formatting follows 5etools' "classic"
style hint, which produces the familiar 2014-era phrasing ("1 action",
"3rd-level evocation") regardless of whether the spell came from a 2014 or 2024
source. That keeps exported markdown consistent across editions.

Functions here may emit ``{@tag}`` markup, exactly as upstream does for
concentration. Callers pass the result through the tag renderer.
"""

from __future__ import annotations

from typing import Any

SCHOOLS = {
    "A": "Abjuration",
    "C": "Conjuration",
    "D": "Divination",
    "E": "Enchantment",
    "I": "Illusion",
    "N": "Necromancy",
    "T": "Transmutation",
    "V": "Evocation",
    "P": "Psionic",
}

# Range and distance types that render as a bare label with no amount.
_BARE_RANGE_TYPES = {
    "self": "Self",
    "sight": "Sight",
    "unlimited": "Unlimited",
    "plane": "Unlimited on the same plane",
    "special": "Special",
    "touch": "Touch",
}

# Range types that describe an area originating from the caster.
_AREA_RANGE_TYPES = {
    "line",
    "cube",
    "cone",
    "emanation",
    "radius",
    "sphere",
    "hemisphere",
    "cylinder",
}

_SINGLETON_UNITS = {
    "inches": "inch",
    "feet": "foot",
    "yards": "yard",
    "miles": "mile",
}

_END_TYPES = {
    "dispel": "dispelled",
    "trigger": "triggered",
    "discharge": "discharged",
}

# Time units that read naturally without a leading "1".
_ORDINALS = {1: "st", 2: "nd", 3: "rd"}


def join_conjunct(parts: list[str], joiner: str = ", ", last: str = " or ") -> str:
    """Join parts the way upstream's `joinConjunct` does, without an Oxford comma."""
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return last.join(parts)
    return joiner.join(parts[:-1]) + last + parts[-1]


def singleton_unit(unit: str | None) -> str | None:
    """Singularize a distance unit: feet to foot, miles to mile."""
    if not unit:
        return unit
    if unit in _SINGLETON_UNITS:
        return _SINGLETON_UNITS[unit]
    return unit[:-1] if unit.endswith("s") else unit


def ordinal(n: int) -> str:
    """1 to 1st, 2 to 2nd, 11 to 11th."""
    suffix = "th" if 10 <= n % 100 <= 20 else _ORDINALS.get(n % 10, "th")
    return f"{n}{suffix}"


def school_to_full(school: str | None) -> str:
    """Map a single-letter school code to its full name."""
    if not school:
        return ""
    return SCHOOLS.get(school, school)


def level_to_full(level: int) -> str:
    """0 to Cantrip, 3 to 3rd."""
    return "Cantrip" if level == 0 else ordinal(level)


def level_to_level_text(level: int) -> str:
    """0 to Cantrip, 3 to 3rd-level."""
    return "Cantrip" if level == 0 else f"{ordinal(level)}-level"


def level_school_to_full(level: int, school: str | None) -> str:
    """The statblock subtitle: "3rd-level evocation" or "Evocation cantrip"."""
    full_school = school_to_full(school)
    if level == 0:
        return f"{full_school} cantrip"
    return f"{level_to_level_text(level)} {full_school.lower()}"


def _time_to_full(time: dict[str, Any]) -> str:
    number = time.get("number")
    unit = time.get("unit", "")
    if unit == "bonus":
        unit = "bonus action"
    if not number:
        return unit
    plural = "s" if number > 1 else ""
    return f"{number} {unit}{plural}"


def time_to_full(times: list[dict[str, Any]] | None, meta: dict[str, Any] | None = None) -> str:
    """Format the casting time list.

    A reaction carries a `condition` string that must be appended, and a `note`
    is parenthesized. Ritual is intentionally not folded in here: upstream only
    appends it in non-classic style, and we surface it as its own field.
    """
    if not times:
        return ""
    parts = []
    for time in times:
        text = _time_to_full(time)
        if time.get("condition"):
            text += f", {time['condition']}"
        if time.get("note"):
            text += f" ({time['note']})"
        parts.append(text)
    return join_conjunct(parts)


def _area_range_to_full(spell_range: dict[str, Any]) -> str:
    size = spell_range.get("distance") or {}
    amount = size.get("amount")
    unit = singleton_unit(size.get("type"))
    range_type = spell_range["type"]

    if range_type == "sphere":
        shape = " radius"
    elif range_type == "hemisphere":
        shape = "-radius hemisphere"
    elif range_type == "cylinder":
        shape = "-radius"
    else:
        shape = f" {range_type}"

    suffix = ""
    if range_type == "cylinder":
        secondary_amount = size.get("amountSecondary")
        secondary_type = singleton_unit(size.get("typeSecondary"))
        if secondary_amount is not None and secondary_type is not None:
            suffix = f", {secondary_amount}-{secondary_type}-high"
        suffix += " cylinder"

    return f"Self ({amount}-{unit}{shape}{suffix})"


def range_to_full(spell_range: dict[str, Any] | None) -> str:
    """Format a spell range, covering all 16 observed shapes."""
    if not spell_range:
        return ""
    range_type = spell_range.get("type")

    if range_type == "special":
        return "Special"

    if range_type in _AREA_RANGE_TYPES:
        return _area_range_to_full(spell_range)

    # Remaining case: type == "point", where the distance carries the meaning.
    distance = spell_range.get("distance") or {}
    distance_type = distance.get("type")
    if distance_type in _BARE_RANGE_TYPES:
        return _BARE_RANGE_TYPES[distance_type]

    amount = distance.get("amount")
    if amount == 1:
        return f"1 {singleton_unit(distance_type)}"
    return f"{amount} {distance_type}"


def components_to_full(components: dict[str, Any] | None, level: int = 0) -> str:
    """Format components as "V, S, M (a ball of bat guano and sulfur)"."""
    if not components:
        return "None"
    parts = []
    if components.get("v"):
        parts.append("V")
    if components.get("s"):
        parts.append("S")
    material = components.get("m")
    if material is not None:
        if material is True:
            parts.append("M")
        else:
            text = material.get("text") if isinstance(material, dict) else material
            parts.append(f"M ({text})")
    if components.get("r"):
        parts.append(f"R ({level} gp)")
    return ", ".join(parts) or "None"


def _duration_to_full(duration: dict[str, Any]) -> tuple[str, bool]:
    """Format one duration entry. Returns the text and whether it used a sub-or."""
    condition = f" ({duration['condition']})" if duration.get("condition") else ""
    duration_type = duration.get("type")

    if duration_type == "special":
        if duration.get("concentration"):
            return "{@status Concentration}", False
        return f"Special{condition}", False

    if duration_type == "instant":
        return f"Instantaneous{condition}", False

    if duration_type == "timed":
        inner = duration.get("duration") or {}
        amount = inner.get("amount")
        unit = inner.get("type", "")
        unit_text = unit if amount == 1 else f"{unit}s"
        if duration.get("concentration"):
            prefix = "{@status Concentration}, up to "
        elif inner.get("upTo"):
            prefix = "Up to "
        else:
            prefix = ""
        return f"{prefix}{amount} {unit_text}{condition}", False

    if duration_type == "permanent":
        ends = duration.get("ends")
        if not ends:
            return f"Permanent{condition}", False
        ends_text = join_conjunct([_END_TYPES.get(e, e) for e in ends])
        return f"Until {ends_text}{condition}", len(ends) > 1

    return condition.strip() or "", False


def duration_to_full(durations: list[dict[str, Any]] | None) -> str:
    """Format the duration list, matching upstream's joiner and "(see below)" suffix."""
    if not durations:
        return ""
    parts = []
    has_sub_or = False
    for duration in durations:
        text, sub_or = _duration_to_full(duration)
        parts.append(text)
        has_sub_or = has_sub_or or sub_or
    joiner = "; " if has_sub_or else ", "
    out = join_conjunct(parts, joiner=joiner)
    if len(durations) > 1:
        out += " (see below)"
    return out


def is_concentration(durations: list[dict[str, Any]] | None) -> bool:
    """Concentration lives on a duration entry, not at the top level of the spell."""
    if not durations:
        return False
    return any(d.get("concentration") for d in durations)
