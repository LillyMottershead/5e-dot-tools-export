"""Snapshot tests for the markdown renderer.

Upstream ships weekly, so the point of these is to turn a data or renderer
change into a reviewable diff rather than a silent shift in output.

Each fixture is hand-written but mirrors the structure of a real spell that
exercises that path; the real spell is named in the docstring so the shape can
be re-checked upstream. No upstream text is copied, per docs/DESIGN.md
section 2.

Regenerate with: uv run pytest --snapshot-update
"""

import pytest

from fivet.models import Spell
from fivet.render.markdown import render_spell
from fivet.render.tags import LinkStyle

BASE = {
    "name": "Sample Spell",
    "source": "XPHB",
    "page": 1,
    "level": 1,
    "school": "V",
    "time": [{"number": 1, "unit": "action"}],
    "range": {"type": "point", "distance": {"type": "feet", "amount": 30}},
    "components": {"v": True, "s": True},
    "duration": [{"type": "instant"}],
    "entries": ["It does a thing."],
}


def spell(**overrides) -> Spell:
    record = {**BASE, **overrides}
    parsed = Spell.model_validate(record)
    parsed.classes = overrides.pop("_classes", ["Wizard"])
    return parsed


CASES = {
    # Shape of Fireball [XPHB]: scaling plus a cross-reference.
    "scaling_and_references": spell(
        name="Scaling Burst",
        level=3,
        entries=[
            "Each creature in a 20-foot-radius {@variantrule Sphere [Area of Effect]|XPHB|Sphere} "
            "makes a Dexterity saving throw, taking {@damage 8d6} Fire damage on a failure.",
            "Flammable objects start {@hazard burning|XPHB}.",
        ],
        entriesHigherLevel=[
            {
                "type": "entries",
                "name": "Using a Higher-Level Spell Slot",
                "entries": ["The damage increases by {@scaledamage 8d6|3-9|1d6} per slot level."],
            }
        ],
    ),
    # Shape of Chaos Bolt [XGE]: a table with rollable cells.
    "table_with_rollable_cells": spell(
        name="Table Spell",
        entries=[
            "Roll for the effect.",
            {
                "type": "table",
                "caption": "Table Spell",
                "colLabels": ["{@dice d4}", "Effect"],
                "rows": [
                    [{"type": "cell", "roll": {"exact": 1}}, "First"],
                    [{"type": "cell", "roll": {"min": 2, "max": 3}}, "Second"],
                    [{"type": "cell", "roll": {"exact": 4}}, "{@creature test beast|xphb|Beast}"],
                ],
            },
        ],
    ),
    # Shape of Absorb Elements [XGE]: a reaction with a trigger condition.
    "reaction_with_condition": spell(
        name="Reactive Guard",
        time=[{"number": 1, "unit": "reaction", "condition": "which you take when struck"}],
        entries=["You ward yourself."],
    ),
    # Shape of Alustriel's Mooncloak [FRHoF]: an emanation area range.
    "emanation_range": spell(
        name="Emanating Aura",
        range={"type": "emanation", "distance": {"type": "feet", "amount": 20}},
        duration=[
            {"type": "timed", "duration": {"type": "minute", "amount": 10}, "concentration": True}
        ],
    ),
    # Shape of Arcane Lock [PHB]: permanent until dispelled.
    "permanent_until_dispelled": spell(
        name="Lasting Seal",
        duration=[{"type": "permanent", "ends": ["dispel"]}],
    ),
    # Shape of Alarm [PHB/XPHB]: a ritual with a list.
    "ritual_with_list": spell(
        name="Listed Ritual",
        meta={"ritual": True},
        entries=[
            "You choose one of the following:",
            {
                "type": "list",
                "style": "list-hang-notitle",
                "items": [
                    {"type": "item", "name": "Audible", "entries": ["You hear a chime."]},
                    {"type": "item", "name": "Mental", "entries": ["You feel a ping."]},
                ],
            },
        ],
    ),
    # Shape of Augury [PHB]: a chance tag.
    "chance_tag": spell(
        name="Uncertain Omen",
        entries=["There is a {@chance 25|||Bad reading!|Good reading} of a false result."],
    ),
    # Shape of Animal Messenger [XPHB]: a filter tag.
    "filter_tag": spell(
        name="Beast Caller",
        entries=["You summon {@filter any beast|bestiary|type=beast|miscellaneous=!swarm}."],
    ),
    # Shape of Find Greater Steed [XGE]: an inset block.
    "inset_block": spell(
        name="Inset Spell",
        entries=[
            "You call a mount.",
            {"type": "inset", "name": "A Caution", "entries": ["Treat it kindly."]},
        ],
    ),
    # Shape of Control Flames [XGE]: several durations.
    "multiple_durations": spell(
        name="Varied Duration",
        duration=[
            {"type": "instant"},
            {"type": "timed", "duration": {"type": "hour", "amount": 1}},
        ],
    ),
    # Shape of Acid Splash [PHB]: a cantrip.
    "cantrip": spell(name="Minor Splash", level=0, school="C"),
    # Shape of Etherealness [PHB]: an up-to duration without concentration.
    "up_to_duration": spell(
        name="Timed Step",
        duration=[{"type": "timed", "duration": {"type": "hour", "amount": 8, "upTo": True}}],
    ),
    # Shape of Gift of Gab [AI]: a royalty component.
    "royalty_component": spell(
        name="Costly Word",
        level=2,
        components={"v": True, "r": True},
    ),
    # Defensive: a material component with no description text.
    "material_without_text": spell(
        name="Vague Material",
        components={"v": True, "s": True, "m": True},
    ),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_obsidian_snapshot(case, snapshot):
    assert render_spell(CASES[case], template="obsidian", data_version="vTEST") == snapshot


@pytest.mark.parametrize("template", ["plain", "compact"])
def test_other_templates_snapshot(template, snapshot):
    assert (
        render_spell(CASES["scaling_and_references"], template=template, data_version="vTEST")
        == snapshot
    )


@pytest.mark.parametrize("links", list(LinkStyle))
def test_link_styles_snapshot(links, snapshot):
    assert (
        render_spell(CASES["scaling_and_references"], links=links, data_version="vTEST") == snapshot
    )
