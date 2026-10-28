"""Tests for the SQLite index, lookup and search."""

import sqlite3

import pytest

from fivet.config import Settings
from fivet.store import MatchKind, Store, StoreMissingError, load_spells


class TestBuild:
    def test_indexes_every_spell(self, store, spell_set):
        assert store.count() == len(spell_set)

    def test_stores_meta(self, store):
        assert store.meta()["version"] == "v0.0.1"

    def test_records_round_trip_through_json(self, store):
        spell = store.by_name("Test Blast")[0]
        assert spell.entries
        assert spell.casting_time == "1 action"

    def test_extra_fields_survive_the_round_trip(self, tmp_path):
        """Storing records verbatim is the point; nothing may be lost in the index."""
        from fivet.models import Spell

        spell = Spell.model_validate(
            {"name": "X", "source": "XPHB", "level": 1, "someNewField": 42}
        )
        built = Store.build(tmp_path / "i.db", [spell])
        with Store(built.path) as store:
            assert store.by_name("X")[0].model_extra["someNewField"] == 42

    def test_build_is_atomic(self, tmp_path, spell_set):
        """A rebuild must not leave a truncated index if it dies partway."""
        path = tmp_path / "index.db"
        Store.build(path, spell_set)
        assert not path.with_suffix(".db.tmp").exists()
        Store.build(path, spell_set[:2])
        with Store(path) as store:
            assert store.count() == 2

    def test_missing_index_raises_a_pointed_error(self, tmp_path):
        with pytest.raises(StoreMissingError):
            Store(tmp_path / "absent.db").count()

    def test_the_store_opens_read_only(self, store):
        with pytest.raises(sqlite3.OperationalError):
            store.connection.execute("DELETE FROM entity")


class TestListings:
    def test_sources_are_counted(self, store):
        counts = dict(store.sources())
        assert counts["XPHB"] == 2
        assert counts["PHB"] == 2

    def test_names_are_unique_and_sorted(self, store):
        names = store.names()
        assert names == sorted(names)
        assert len(names) == len(set(names))


class TestResolution:
    def test_exact_match(self, store):
        match = store.resolve("Quiet Ward")
        assert match.spell.name == "Quiet Ward"
        assert match.kind is MatchKind.EXACT

    def test_match_is_case_insensitive(self, store):
        assert store.resolve("quiet ward").spell.name == "Quiet Ward"

    def test_prefix_match(self, store):
        match = store.resolve("Quiet")
        assert match.spell.name == "Quiet Ward"
        assert match.kind is MatchKind.PREFIX

    def test_fuzzy_match_on_a_typo(self, store):
        """The reflex use is `5et spell firebal`, so typos must resolve."""
        match = store.resolve("Quiet Wrad")
        assert match.spell.name == "Quiet Ward"
        assert match.kind is MatchKind.FUZZY

    def test_unknown_name_resolves_to_nothing(self, store):
        assert store.resolve("Nonexistent Incantation") is None

    def test_a_high_cutoff_suppresses_fuzzy_matching(self, store):
        settings = Settings(fuzzy_cutoff=100)
        assert store.resolve("Quiet Wrad", settings) is None

    def test_fts_syntax_characters_do_not_break_lookup(self, store):
        """User input must never reach FTS5 as query syntax."""
        for hostile in ['"', "(", "fire*", "a AND b", "NEAR/", "^x"]:
            store.resolve(hostile)


class TestAmbiguity:
    def test_2024_source_wins_by_default(self, store):
        match = store.resolve("Test Blast")
        assert match.spell.source == "XPHB"
        assert match.is_ambiguous
        assert [s.source for s in match.alternatives] == ["PHB"]

    def test_configured_priority_inverts_the_choice(self, store):
        settings = Settings(source_priority=["PHB", "XPHB"])
        match = store.resolve("Test Blast", settings)
        assert match.spell.source == "PHB"

    def test_explicit_source_overrides_priority(self, store):
        match = store.resolve("Test Blast", source="PHB")
        assert match.spell.source == "PHB"
        assert not match.is_ambiguous

    def test_explicit_source_is_case_insensitive(self, store):
        assert store.resolve("Test Blast", source="phb").spell.source == "PHB"

    def test_unavailable_source_resolves_to_nothing(self, store):
        assert store.resolve("Test Blast", source="XGE") is None

    def test_unambiguous_spell_has_no_alternatives(self, store):
        assert not store.resolve("Quiet Ward").is_ambiguous


class TestSearch:
    def test_unfiltered_search_returns_everything(self, store, spell_set):
        assert len(store.search()) == len(spell_set)

    def test_filter_by_level(self, store):
        assert {s.level for s in store.search(level=3)} == {3}

    def test_filter_by_school_code(self, store):
        assert {s.school for s in store.search(school="A")} == {"A"}

    def test_filter_by_school_full_name(self, store):
        """A user types "evocation", not "V"."""
        assert {s.school for s in store.search(school="evocation")} == {"V"}

    def test_unknown_school_matches_nothing(self, store):
        assert store.search(school="pyromancy") == []

    def test_filter_by_class(self, store):
        names = {s.name for s in store.search(class_name="Druid")}
        assert names == {"Testing Winds"}

    def test_filter_by_source(self, store):
        assert {s.source for s in store.search(source="XGE")} == {"XGE"}

    def test_text_query_matches_a_name_prefix(self, store):
        assert {s.name for s in store.search(query="Ward")} == {"Quiet Ward", "Loud Ward"}

    def test_filters_combine(self, store):
        results = store.search(query="Ward", level=1)
        assert [s.name for s in results] == ["Quiet Ward"]

    def test_results_are_ordered_deterministically(self, store):
        results = store.search(query="Test")
        assert [(s.name, s.source) for s in results] == sorted((s.name, s.source) for s in results)

    def test_limit_is_respected(self, store):
        assert len(store.search(limit=2)) == 2

    def test_hostile_query_returns_no_results_rather_than_raising(self, store):
        assert store.search(query='"') == []


class TestLoadSpells:
    def test_attaches_classes_from_the_sources_index(self):
        raw = {"XPHB": [{"name": "Fireball", "source": "XPHB", "level": 3}]}
        classes = {("XPHB", "fireball"): ["Sorcerer", "Wizard"]}
        spells = load_spells(raw, classes)
        assert spells[0].classes == ["Sorcerer", "Wizard"]

    def test_the_join_key_is_source_and_name_not_name_alone(self):
        """The 2014 and 2024 versions of a spell can list different classes."""
        raw = {
            "XPHB": [{"name": "Fireball", "source": "XPHB", "level": 3}],
            "PHB": [{"name": "Fireball", "source": "PHB", "level": 3}],
        }
        classes = {
            ("XPHB", "fireball"): ["Wizard"],
            ("PHB", "fireball"): ["Sorcerer", "Wizard"],
        }
        spells = load_spells(raw, classes)
        by_source = {s.source: s.classes for s in spells}
        assert by_source["XPHB"] == ["Wizard"]
        assert by_source["PHB"] == ["Sorcerer", "Wizard"]

    def test_missing_class_data_leaves_the_list_empty(self):
        raw = {"XPHB": [{"name": "Fireball", "source": "XPHB", "level": 3}]}
        assert load_spells(raw, {})[0].classes == []
