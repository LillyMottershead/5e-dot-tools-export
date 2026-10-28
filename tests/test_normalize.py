"""Tests for normalize.py.

The mappings under test are closed enumerations (docs/DESIGN.md section 3.2), so
these tests aim to be exhaustive rather than representative. Fixtures are
hand-written metadata shapes; no spell text is copied from upstream.
"""

import pytest

from fivet import normalize as n


class TestJoinConjunct:
    @pytest.mark.parametrize(
        ("parts", "expected"),
        [
            ([], ""),
            (["a"], "a"),
            (["a", "b"], "a or b"),
            (["a", "b", "c"], "a, b or c"),
            (["a", "b", "c", "d"], "a, b, c or d"),
        ],
    )
    def test_matches_upstream_joiner(self, parts, expected):
        assert n.join_conjunct(parts) == expected

    def test_custom_joiner(self):
        assert n.join_conjunct(["a", "b", "c"], joiner="; ") == "a; b or c"


class TestSingletonUnit:
    @pytest.mark.parametrize(
        ("unit", "expected"),
        [
            ("feet", "foot"),
            ("miles", "mile"),
            ("inches", "inch"),
            ("yards", "yard"),
            ("rounds", "round"),
            ("minute", "minute"),
            (None, None),
            ("", ""),
        ],
    )
    def test_singularizes(self, unit, expected):
        assert n.singleton_unit(unit) == expected


class TestOrdinal:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1, "1st"),
            (2, "2nd"),
            (3, "3rd"),
            (4, "4th"),
            (9, "9th"),
            (11, "11th"),
            (12, "12th"),
            (13, "13th"),
            (21, "21st"),
        ],
    )
    def test_suffixes(self, value, expected):
        assert n.ordinal(value) == expected


class TestSchool:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("A", "Abjuration"),
            ("C", "Conjuration"),
            ("D", "Divination"),
            ("E", "Enchantment"),
            ("I", "Illusion"),
            ("N", "Necromancy"),
            ("T", "Transmutation"),
            ("V", "Evocation"),
            ("P", "Psionic"),
        ],
    )
    def test_all_codes(self, code, expected):
        """All eight spell schools occur in the data; P exists upstream but in no spell."""
        assert n.school_to_full(code) == expected

    def test_unknown_code_passes_through(self):
        assert n.school_to_full("Z") == "Z"

    def test_missing_is_empty(self):
        assert n.school_to_full(None) == ""


class TestLevel:
    @pytest.mark.parametrize(
        ("level", "full", "level_text"),
        [
            (0, "Cantrip", "Cantrip"),
            (1, "1st", "1st-level"),
            (3, "3rd", "3rd-level"),
            (9, "9th", "9th-level"),
        ],
    )
    def test_level_forms(self, level, full, level_text):
        assert n.level_to_full(level) == full
        assert n.level_to_level_text(level) == level_text

    def test_subtitle_for_levelled_spell(self):
        assert n.level_school_to_full(3, "V") == "3rd-level evocation"

    def test_subtitle_for_cantrip_inverts_word_order(self):
        assert n.level_school_to_full(0, "T") == "Transmutation cantrip"


class TestCastingTime:
    @pytest.mark.parametrize(
        ("times", "expected"),
        [
            ([{"number": 1, "unit": "action"}], "1 action"),
            ([{"number": 1, "unit": "bonus"}], "1 bonus action"),
            ([{"number": 1, "unit": "minute"}], "1 minute"),
            ([{"number": 10, "unit": "minute"}], "10 minutes"),
            ([{"number": 1, "unit": "hour"}], "1 hour"),
            ([{"number": 8, "unit": "hour"}], "8 hours"),
        ],
    )
    def test_all_observed_units(self, times, expected):
        assert n.time_to_full(times) == expected

    def test_reaction_appends_its_condition(self):
        """A reaction is meaningless without its trigger, so the condition is required."""
        times = [{"number": 1, "unit": "reaction", "condition": "which you take when poked"}]
        assert n.time_to_full(times) == "1 reaction, which you take when poked"

    def test_note_is_parenthesized(self):
        times = [{"number": 1, "unit": "action", "note": "see below"}]
        assert n.time_to_full(times) == "1 action (see below)"

    def test_multiple_times_are_joined_with_or(self):
        times = [{"number": 1, "unit": "action"}, {"number": 1, "unit": "minute"}]
        assert n.time_to_full(times) == "1 action or 1 minute"

    def test_empty(self):
        assert n.time_to_full(None) == ""
        assert n.time_to_full([]) == ""


class TestRange:
    @pytest.mark.parametrize(
        ("spell_range", "expected"),
        [
            ({"type": "point", "distance": {"type": "feet", "amount": 150}}, "150 feet"),
            ({"type": "point", "distance": {"type": "feet", "amount": 1}}, "1 foot"),
            ({"type": "point", "distance": {"type": "miles", "amount": 5}}, "5 miles"),
            ({"type": "point", "distance": {"type": "miles", "amount": 1}}, "1 mile"),
            ({"type": "point", "distance": {"type": "touch"}}, "Touch"),
            ({"type": "point", "distance": {"type": "self"}}, "Self"),
            ({"type": "point", "distance": {"type": "sight"}}, "Sight"),
            ({"type": "point", "distance": {"type": "unlimited"}}, "Unlimited"),
            (
                {"type": "point", "distance": {"type": "plane"}},
                "Unlimited on the same plane",
            ),
            ({"type": "special"}, "Special"),
        ],
    )
    def test_point_and_special_ranges(self, spell_range, expected):
        assert n.range_to_full(spell_range) == expected

    @pytest.mark.parametrize(
        ("spell_range", "expected"),
        [
            (
                {"type": "emanation", "distance": {"type": "feet", "amount": 20}},
                "Self (20-foot emanation)",
            ),
            (
                {"type": "radius", "distance": {"type": "feet", "amount": 10}},
                "Self (10-foot radius)",
            ),
            (
                {"type": "cone", "distance": {"type": "feet", "amount": 60}},
                "Self (60-foot cone)",
            ),
            (
                {"type": "line", "distance": {"type": "feet", "amount": 100}},
                "Self (100-foot line)",
            ),
            (
                {"type": "cube", "distance": {"type": "feet", "amount": 10}},
                "Self (10-foot cube)",
            ),
            (
                {"type": "sphere", "distance": {"type": "feet", "amount": 40}},
                "Self (40-foot radius)",
            ),
            (
                {"type": "hemisphere", "distance": {"type": "feet", "amount": 30}},
                "Self (30-foot-radius hemisphere)",
            ),
            (
                {"type": "sphere", "distance": {"type": "miles", "amount": 1}},
                "Self (1-mile radius)",
            ),
        ],
    )
    def test_area_ranges(self, spell_range, expected):
        """Area ranges render as Self plus a parenthesized shape, per upstream."""
        assert n.range_to_full(spell_range) == expected

    def test_cylinder_carries_a_height(self):
        """Cylinder is homebrew-only upstream, but the shape is defined, so handle it."""
        spell_range = {
            "type": "cylinder",
            "distance": {
                "type": "feet",
                "amount": 20,
                "amountSecondary": 40,
                "typeSecondary": "feet",
            },
        }
        assert n.range_to_full(spell_range) == "Self (20-foot-radius, 40-foot-high cylinder)"

    def test_empty(self):
        assert n.range_to_full(None) == ""


class TestComponents:
    @pytest.mark.parametrize(
        ("components", "expected"),
        [
            ({"v": True}, "V"),
            ({"s": True}, "S"),
            ({"v": True, "s": True}, "V, S"),
            ({"v": True, "s": True, "m": True}, "V, S, M"),
            ({"m": "a pinch of dust"}, "M (a pinch of dust)"),
            ({"v": True, "m": {"text": "a silver rod"}}, "V, M (a silver rod)"),
            (None, "None"),
            ({}, "None"),
        ],
    )
    def test_component_combinations(self, components, expected):
        assert n.components_to_full(components) == expected

    def test_royalty_component_uses_spell_level(self):
        assert n.components_to_full({"v": True, "r": True}, level=3) == "V, R (3 gp)"


class TestDuration:
    @pytest.mark.parametrize(
        ("durations", "expected"),
        [
            ([{"type": "instant"}], "Instantaneous"),
            (
                [{"type": "timed", "duration": {"type": "minute", "amount": 10}}],
                "10 minutes",
            ),
            (
                [{"type": "timed", "duration": {"type": "hour", "amount": 1}}],
                "1 hour",
            ),
            (
                [{"type": "timed", "duration": {"type": "round", "amount": 1}}],
                "1 round",
            ),
            (
                [{"type": "timed", "duration": {"type": "day", "amount": 7}}],
                "7 days",
            ),
            ([{"type": "permanent"}], "Permanent"),
            ([{"type": "permanent", "ends": ["dispel"]}], "Until dispelled"),
            ([{"type": "special"}], "Special"),
        ],
    )
    def test_observed_duration_shapes(self, durations, expected):
        assert n.duration_to_full(durations) == expected

    def test_concentration_emits_a_status_tag(self):
        """Upstream emits {@status Concentration}; the tag layer renders it onward."""
        durations = [
            {"type": "timed", "duration": {"type": "minute", "amount": 1}, "concentration": True}
        ]
        assert n.duration_to_full(durations) == "{@status Concentration}, up to 1 minute"

    def test_up_to_without_concentration(self):
        durations = [{"type": "timed", "duration": {"type": "hour", "amount": 8, "upTo": True}}]
        assert n.duration_to_full(durations) == "Up to 8 hours"

    def test_multiple_end_conditions_join_with_or(self):
        durations = [{"type": "permanent", "ends": ["dispel", "trigger"]}]
        assert n.duration_to_full(durations) == "Until dispelled or triggered"

    def test_multiple_durations_get_see_below(self):
        durations = [
            {"type": "timed", "duration": {"type": "minute", "amount": 1}},
            {"type": "permanent", "ends": ["dispel"]},
        ]
        assert n.duration_to_full(durations) == "1 minute or Until dispelled (see below)"

    def test_sub_or_switches_the_outer_joiner_to_semicolons(self):
        """When an entry itself contains "or", upstream switches the outer joiner."""
        durations = [
            {"type": "instant"},
            {"type": "permanent", "ends": ["dispel", "trigger"]},
            {"type": "special"},
        ]
        result = n.duration_to_full(durations)
        assert result == "Instantaneous; Until dispelled or triggered or Special (see below)"

    def test_condition_is_parenthesized(self):
        durations = [{"type": "instant", "condition": "or until you move"}]
        assert n.duration_to_full(durations) == "Instantaneous (or until you move)"

    def test_empty(self):
        assert n.duration_to_full(None) == ""


class TestIsConcentration:
    def test_detects_concentration_on_a_duration_entry(self):
        durations = [
            {"type": "timed", "duration": {"type": "minute", "amount": 1}, "concentration": True}
        ]
        assert n.is_concentration(durations) is True

    def test_false_when_absent(self):
        assert n.is_concentration([{"type": "instant"}]) is False
        assert n.is_concentration(None) is False
