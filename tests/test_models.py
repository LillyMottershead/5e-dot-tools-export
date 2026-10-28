"""Tests for the lax spell model."""

import pytest
from pydantic import ValidationError

from fivet.models import Spell


class TestParsing:
    def test_parses_a_full_record(self, raw_spell):
        spell = Spell.model_validate(raw_spell)
        assert spell.name == "Test Blast"
        assert spell.source == "XPHB"
        assert spell.level == 3

    def test_camel_case_fields_are_aliased(self, raw_spell):
        spell = Spell.model_validate(raw_spell)
        assert spell.entries_higher_level[0]["name"] == "Using a Higher-Level Spell Slot"
        assert spell.damage_inflict == ["fire"]
        assert spell.area_tags == ["S"]

    def test_unknown_upstream_fields_are_kept_not_rejected(self):
        """Upstream ships weekly; a new field must not break sync."""
        spell = Spell.model_validate(
            {"name": "X", "source": "XPHB", "level": 1, "someNewFieldFrom2027": 42}
        )
        assert spell.name == "X"
        assert spell.model_extra["someNewFieldFrom2027"] == 42

    def test_a_minimal_record_needs_only_identity_and_level(self):
        spell = Spell.model_validate({"name": "X", "source": "XPHB", "level": 0})
        assert spell.school_full == ""
        assert spell.casting_time == ""
        assert spell.range_text == ""

    @pytest.mark.parametrize("missing", ["name", "source", "level"])
    def test_identity_fields_are_required(self, raw_spell, missing):
        del raw_spell[missing]
        with pytest.raises(ValidationError):
            Spell.model_validate(raw_spell)


class TestDerivedProperties:
    def test_levelled_spell(self, raw_spell):
        spell = Spell.model_validate(raw_spell)
        assert spell.level_text == "3rd-level"
        assert spell.school_full == "Evocation"
        assert spell.subtitle == "3rd-level evocation"
        assert spell.casting_time == "1 action"
        assert spell.range_text == "150 feet"
        assert spell.components_text == "V, S, M (a scrap of parchment)"
        assert spell.duration_text == "Instantaneous"
        assert spell.is_concentration is False
        assert spell.is_ritual is False

    def test_cantrip_with_concentration_and_ritual(self, raw_cantrip):
        spell = Spell.model_validate(raw_cantrip)
        assert spell.level_text == "Cantrip"
        assert spell.subtitle == "Transmutation cantrip"
        assert spell.range_text == "Touch"
        assert spell.is_concentration is True
        assert spell.is_ritual is True

    def test_duration_text_carries_markup_for_the_tag_layer(self, raw_cantrip):
        """Upstream emits concentration as a tag; rendering happens downstream."""
        spell = Spell.model_validate(raw_cantrip)
        assert spell.duration_text == "{@status Concentration}, up to 1 minute"

    def test_uid_matches_the_upstream_form(self, raw_spell):
        assert Spell.model_validate(raw_spell).uid == "test blast|xphb"

    def test_classes_default_to_empty_since_they_come_from_sources_json(self, raw_spell):
        assert Spell.model_validate(raw_spell).classes == []
