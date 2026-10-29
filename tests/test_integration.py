"""Invariant checks against a real synced cache.

These skip unless a cache exists, so the suite stays offline and fast by
default. They assert invariants rather than content, both because upstream
changes weekly and because no upstream text may be committed to this
repository (docs/DESIGN.md section 2).

Run against a real cache with:
    uv run 5et sync && uv run pytest tests/test_integration.py
or point at a specific one with FIVET_CACHE_DIR.
"""

import re

import pytest

from fivet import config, sync
from fivet.config import Edition
from fivet.render.markdown import render_spell
from fivet.render.tags import LinkStyle
from fivet.store import Store

UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


@pytest.fixture(scope="module")
def real_store():
    path = config.cache_dir() / sync.INDEX_DB
    if not path.is_file():
        pytest.skip(f"No synced cache at {path}; run `5et sync` to enable these tests.")
    with Store(path) as store:
        yield store


@pytest.fixture(scope="module")
def all_spells(real_store):
    return real_store.search(limit=100_000)


def test_the_cache_holds_a_plausible_corpus(all_spells):
    assert len(all_spells) > 500


def test_every_spell_renders_in_every_template_and_link_style(all_spells):
    for spell in all_spells:
        for template in ("obsidian", "plain", "compact"):
            for links in LinkStyle:
                render_spell(spell, template=template, links=links, data_version="vTEST")


def test_no_markup_leaks_into_rendered_output(all_spells):
    offenders = [
        spell.uid for spell in all_spells if "{@" in render_spell(spell, data_version="vTEST")
    ]
    assert offenders == []


def test_every_spell_has_renderable_metadata(all_spells):
    missing = [
        spell.uid
        for spell in all_spells
        if not (spell.subtitle and spell.casting_time and spell.range_text and spell.duration_text)
    ]
    assert missing == []


def test_frontmatter_stays_single_line_per_key(all_spells):
    """A stray newline in a value would silently corrupt the frontmatter block."""
    for spell in all_spells:
        text = render_spell(spell, data_version="vTEST")
        block = text.split("---\n", 2)[1]
        for line in block.splitlines():
            if line.strip():
                assert ":" in line, f"{spell.uid}: orphaned frontmatter line {line!r}"


def test_tables_are_not_ragged(all_spells):
    """A piped wikilink inside a cell is the case that would break this."""
    for spell in all_spells:
        for links in LinkStyle:
            text = render_spell(spell, links=links, data_version="vTEST")
            for block in text.split("\n\n"):
                if not block.startswith("|"):
                    continue
                widths = {len(UNESCAPED_PIPE.findall(line)) for line in block.splitlines()}
                assert len(widths) == 1, f"{spell.uid}: ragged table {widths}"


def test_source_ambiguity_resolves_deterministically(real_store):
    for name in real_store.names():
        first = real_store.resolve(name)
        second = real_store.resolve(name)
        assert first.spell.uid == second.spell.uid


def test_the_index_records_its_data_version(real_store):
    assert real_store.meta().get("version", "").startswith("v")


@pytest.mark.parametrize("edition", list(Edition))
def test_an_edition_scope_excludes_only_the_other_handbook(real_store, edition):
    scoped = real_store.search(edition=edition, limit=100_000)
    sources = {spell.source.upper() for spell in scoped}
    assert edition.excluded_source not in sources
    assert edition.phb in sources
    assert len(sources) > 2, "supplements must survive an edition scope"


@pytest.mark.parametrize("edition", list(Edition))
def test_every_scoped_name_still_resolves_inside_its_edition(real_store, edition):
    """A name the scope keeps must resolve, and never to the excluded book."""
    wrong = [
        name
        for name in real_store.names(edition=edition)
        if (match := real_store.resolve(name, edition=edition)) is None
        or match.spell.source.upper() == edition.excluded_source
    ]
    assert wrong == []


def test_a_scope_only_loses_names_unique_to_the_excluded_handbook(real_store):
    """Nothing available elsewhere may disappear when an edition is picked."""
    for edition in Edition:
        lost = set(real_store.names()) - set(real_store.names(edition=edition))
        elsewhere = {
            spell.name
            for spell in real_store.search(limit=100_000)
            if spell.source.upper() != edition.excluded_source
        }
        assert not (lost & elsewhere)
