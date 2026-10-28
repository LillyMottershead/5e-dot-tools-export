"""Tests for the rich terminal presentation.

Output is checked by rendering the renderable to plain text with a fixed width,
so these assert content rather than exact box drawing.
"""

from rich.console import Console

from fivet.models import Spell
from fivet.render.terminal import search_table, source_table, spell_renderable


def to_text(renderable, width: int = 100) -> str:
    console = Console(width=width, no_color=True, legacy_windows=False, file=None, record=True)
    console.print(renderable)
    return console.export_text()


class TestSpellRenderable:
    def test_shows_the_name_and_subtitle(self, raw_spell):
        text = to_text(spell_renderable(Spell.model_validate(raw_spell)))
        assert "Test Blast" in text
        assert "3rd-level evocation" in text

    def test_shows_the_metadata_fields(self, raw_spell):
        text = to_text(spell_renderable(Spell.model_validate(raw_spell)))
        for label in ("Casting Time", "Range", "Components", "Duration"):
            assert label in text
        assert "150 feet" in text

    def test_shows_the_description_and_higher_levels(self, raw_spell):
        text = to_text(spell_renderable(Spell.model_validate(raw_spell)))
        assert "Dexterity saving throw" in text
        assert "Using a Higher-Level Spell Slot" in text

    def test_uses_plain_links_because_wikilinks_read_as_noise(self, raw_spell):
        text = to_text(spell_renderable(Spell.model_validate(raw_spell)))
        assert "[[" not in text
        assert "burning" in text

    def test_no_markup_leaks(self, raw_spell):
        assert "{@" not in to_text(spell_renderable(Spell.model_validate(raw_spell)))

    def test_footer_carries_source_and_data_version(self, raw_spell):
        text = to_text(spell_renderable(Spell.model_validate(raw_spell), data_version="v2.39.0"))
        assert "XPHB p.100" in text
        assert "v2.39.0" in text

    def test_concentration_and_ritual_appear_as_tags(self, raw_cantrip):
        text = to_text(spell_renderable(Spell.model_validate(raw_cantrip)))
        assert "concentration" in text
        assert "ritual" in text

    def test_classes_are_listed_when_known(self, raw_spell):
        spell = Spell.model_validate(raw_spell)
        spell.classes = ["Sorcerer", "Wizard"]
        assert "Sorcerer, Wizard" in to_text(spell_renderable(spell))

    def test_a_minimal_spell_still_renders(self):
        spell = Spell.model_validate({"name": "Bare", "source": "XPHB", "level": 1})
        assert "Bare" in to_text(spell_renderable(spell))


class TestTables:
    def test_search_table_lists_each_spell(self, spell_set):
        text = to_text(search_table(spell_set))
        assert "Quiet Ward" in text
        assert "Abjuration" in text

    def test_cantrips_show_as_c_rather_than_zero(self, spell_set):
        text = to_text(search_table(spell_set))
        lines = [line for line in text.splitlines() if "Test Touch" in line]
        assert lines and " C " in lines[0]

    def test_source_table_shows_counts(self):
        text = to_text(source_table([("XPHB", 391), ("PHB", 361)]))
        assert "XPHB" in text
        assert "391" in text
