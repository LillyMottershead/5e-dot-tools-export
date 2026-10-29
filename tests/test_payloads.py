"""Tests for the JSON payload shapes.

The contract these pin down is that `--format json` carries the normalized
display view, under the names the rest of the tool uses, with no raw upstream
key left in it.
"""

from fivet.models import Spell
from fivet.render import payloads
from fivet.render.tags import LinkStyle

# Keys that would mean a raw upstream record leaked into the payload.
RAW_KEYS = {
    "entries",
    "entriesHigherLevel",
    "time",
    "damageInflict",
    "savingThrow",
    "conditionInflict",
    "meta",
}


class TestSpellPayload:
    def test_carries_the_display_fields(self, raw_spell):
        payload = payloads.spell_payload(Spell.model_validate(raw_spell))
        assert payload["name"] == "Test Blast"
        assert payload["level"] == 3
        assert payload["level_text"] == "3rd-level"
        assert payload["school"] == "Evocation"
        assert payload["subtitle"] == "3rd-level evocation"
        assert payload["casting_time"] == "1 action"
        assert payload["range"] == "150 feet"
        assert payload["duration"] == "Instantaneous"
        assert payload["uid"] == "test blast|xphb"

    def test_carries_no_raw_upstream_keys(self, raw_spell):
        payload = payloads.spell_payload(Spell.model_validate(raw_spell))
        assert not RAW_KEYS & set(payload)

    def test_flags_are_booleans_not_strings(self, raw_cantrip):
        payload = payloads.spell_payload(Spell.model_validate(raw_cantrip))
        assert payload["concentration"] is True
        assert payload["ritual"] is True

    def test_markup_is_stripped_from_scalar_fields(self, raw_cantrip):
        """Duration can arrive carrying {@status Concentration}."""
        payload = payloads.spell_payload(Spell.model_validate(raw_cantrip))
        assert "{@" not in payload["duration"]
        assert "Concentration" in payload["duration"]

    def test_prose_is_rendered_markdown(self, raw_spell):
        payload = payloads.spell_payload(Spell.model_validate(raw_spell))
        assert "8d6 Fire damage" in payload["description"]
        assert "{@damage" not in payload["description"]
        assert "Using a Higher-Level Spell Slot" in payload["higher_levels"]

    def test_the_link_style_is_honored(self, raw_spell):
        spell = Spell.model_validate(raw_spell)
        plain = payloads.spell_payload(spell, links=LinkStyle.PLAIN)
        wiki = payloads.spell_payload(spell, links=LinkStyle.WIKILINK)
        assert "[[" not in plain["description"]
        assert "[[" in wiki["description"]

    def test_missing_fields_are_null_not_absent(self):
        spell = Spell.model_validate({"name": "Bare", "source": "XPHB", "level": 1})
        payload = payloads.spell_payload(spell)
        assert payload["page"] is None
        assert payload["description"] == ""
        assert payload["classes"] == []

    def test_the_data_version_is_carried(self, raw_spell):
        payload = payloads.spell_payload(Spell.model_validate(raw_spell), data_version="v1.2.3")
        assert payload["data_version"] == "v1.2.3"


class TestListingPayloads:
    def test_search_payload_counts_and_lists(self, spell_set):
        payload = payloads.search_payload(spell_set, data_version="v1.2.3")
        assert payload["count"] == len(spell_set)
        assert payload["data_version"] == "v1.2.3"
        assert payload["results"][0]["name"] == "Test Blast"
        assert payload["results"][0]["school"] == "Evocation"

    def test_search_payload_reports_an_empty_result_set(self):
        payload = payloads.search_payload([])
        assert payload == {"count": 0, "results": [], "data_version": ""}

    def test_a_row_keeps_the_level_as_a_number(self, raw_cantrip):
        row = payloads.spell_row(Spell.model_validate(raw_cantrip))
        assert row["level"] == 0
        assert row["level_text"] == "Cantrip"

    def test_sources_payload(self):
        payload = payloads.sources_payload([("XPHB", 2), ("PHB", 1)])
        assert payload["sources"] == [
            {"source": "XPHB", "spells": 2},
            {"source": "PHB", "spells": 1},
        ]
