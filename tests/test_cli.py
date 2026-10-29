"""Tests for the command line interface.

All HTTP is mocked; these never reach the network. Each test runs against an
isolated cache and config directory.
"""

import json

import pytest
import respx
from click.testing import CliRunner

from fivet import sync
from fivet.cli import main
from tests.test_sync import VERSION, mock_all


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def synced(isolated_dirs, spell_set):
    """A populated cache, built directly rather than over mocked HTTP."""
    from fivet.store import Store

    cache = isolated_dirs["cache"]
    Store.build(cache / sync.INDEX_DB, spell_set, meta={"version": VERSION})
    (cache / sync.MANIFEST_FILE).write_text(
        json.dumps({"version": VERSION, "fetched_at": "2026-10-28T00:00:00+00:00", "files": {}})
    )
    return cache


class TestTopLevel:
    def test_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "spell" in result.output
        assert "sync" in result.output

    def test_version(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "5et" in result.output


class TestWithoutACache:
    def test_lookup_points_at_sync_and_fails(self, runner, isolated_dirs):
        """A lookup must never download several megabytes as a side effect."""
        result = runner.invoke(main, ["spell", "fireball"])
        assert result.exit_code != 0
        assert "5et sync" in result.output

    def test_search_points_at_sync(self, runner, isolated_dirs):
        result = runner.invoke(main, ["search", "fire"])
        assert result.exit_code != 0
        assert "5et sync" in result.output

    def test_cache_info_reports_empty(self, runner, isolated_dirs):
        result = runner.invoke(main, ["cache", "info"])
        assert result.exit_code == 0
        assert "empty" in result.output


class TestSyncCommand:
    @respx.mock
    def test_sync_reports_what_it_fetched(self, runner, isolated_dirs):
        mock_all(respx)
        result = runner.invoke(main, ["sync"])
        assert result.exit_code == 0
        assert "2" in result.output
        assert VERSION in result.output

    @respx.mock
    def test_sync_with_a_pinned_version(self, runner, isolated_dirs):
        mock_all(respx)
        result = runner.invoke(main, ["sync", "--version", VERSION])
        assert result.exit_code == 0

    @respx.mock
    def test_resync_at_the_same_version_is_a_no_op_without_force(self, runner, isolated_dirs):
        mock_all(respx)
        runner.invoke(main, ["sync", "--version", VERSION])
        result = runner.invoke(main, ["sync", "--version", VERSION])
        assert "Already at" in result.output

    @respx.mock
    def test_force_refetches(self, runner, isolated_dirs):
        mock_all(respx)
        runner.invoke(main, ["sync", "--version", VERSION])
        result = runner.invoke(main, ["sync", "--version", VERSION, "--force"])
        assert "Synced" in result.output

    @respx.mock
    def test_a_sync_failure_is_a_clean_error_not_a_traceback(self, runner, isolated_dirs):
        respx.get(f"{sync.API_BASE}/repos/{sync.REPO}/releases/latest").respond(403)
        result = runner.invoke(main, ["sync"])
        assert result.exit_code != 0
        assert "--version" in result.output
        assert "Traceback" not in result.output


class TestSpellCommand:
    def test_outputs_markdown_when_not_a_tty(self, runner, synced):
        """CliRunner's stdout is not a TTY, which is the piped case."""
        result = runner.invoke(main, ["spell", "Quiet Ward"])
        assert result.exit_code == 0
        assert result.output.startswith("---\n")
        assert "# Quiet Ward" in result.output

    def test_markdown_format_can_be_forced(self, runner, synced):
        result = runner.invoke(main, ["spell", "Quiet Ward", "--format", "md"])
        assert result.output.startswith("---\n")

    def test_rich_format_can_be_forced(self, runner, synced):
        result = runner.invoke(main, ["spell", "Quiet Ward", "--format", "rich"])
        assert result.exit_code == 0
        assert "Quiet Ward" in result.output
        assert not result.output.startswith("---")

    def test_template_selection(self, runner, synced):
        result = runner.invoke(main, ["spell", "Quiet Ward", "-t", "compact"])
        assert result.output.startswith("**Quiet Ward**")

    def test_unknown_template_is_a_clean_error(self, runner, synced):
        result = runner.invoke(main, ["spell", "Quiet Ward", "-t", "nope"])
        assert result.exit_code != 0
        assert "obsidian" in result.output

    def test_link_style_override(self, runner, synced):
        result = runner.invoke(main, ["spell", "Test Blast", "--links", "plain"])
        assert "[[" not in result.output

    def test_unknown_spell_suggests_alternatives(self, runner, synced):
        result = runner.invoke(main, ["spell", "Zzzzz Nonexistent"])
        assert result.exit_code != 0
        assert "No spell matching" in result.output

    def test_a_fuzzy_match_is_noted_on_stderr_not_stdout(self, runner, synced):
        """Markdown on stdout must stay clean enough to redirect into a file."""
        result = runner.invoke(main, ["spell", "Quiet Wrad"])
        assert result.exit_code == 0
        assert result.stdout.startswith("---\n")
        assert "Matched" in result.stderr

    def test_ambiguity_is_noted_on_stderr(self, runner, synced):
        result = runner.invoke(main, ["spell", "Test Blast"])
        assert "also in PHB" in result.stderr
        assert "XPHB" in result.stdout

    def test_source_can_be_chosen_explicitly(self, runner, synced):
        result = runner.invoke(main, ["spell", "Test Blast", "--source", "PHB"])
        assert "source: PHB" in result.output

    def test_an_unavailable_source_is_an_error(self, runner, synced):
        result = runner.invoke(main, ["spell", "Test Blast", "--source", "XGE"])
        assert result.exit_code != 0
        assert "XGE" in result.output

    def test_the_data_version_is_cited_in_output(self, runner, synced):
        result = runner.invoke(main, ["spell", "Quiet Ward"])
        assert f"data_version: {VERSION}" in result.output


class TestEditionFlags:
    """`--2014` and `--2024` on the commands that filter."""

    def test_legacy_picks_the_2014_handbook(self, runner, synced):
        result = runner.invoke(main, ["spell", "Test Blast", "--2014"])
        assert result.exit_code == 0
        assert "source: PHB" in result.stdout

    def test_revised_picks_the_2024_handbook(self, runner, synced):
        result = runner.invoke(main, ["spell", "Test Blast", "--2024"])
        assert result.exit_code == 0
        assert "source: XPHB" in result.stdout

    def test_a_scoped_lookup_is_unambiguous(self, runner, synced):
        """With one handbook ruled out there is nothing to disambiguate."""
        result = runner.invoke(main, ["spell", "Test Blast", "--2014"])
        assert "also in" not in result.stderr

    def test_a_spell_from_the_excluded_handbook_is_an_error_naming_the_edition(
        self, runner, synced
    ):
        result = runner.invoke(main, ["spell", "Testing Winds", "--2014"])
        assert result.exit_code != 0
        assert "2014" in result.output

    def test_supplements_are_unaffected(self, runner, synced):
        for flag in ("--2014", "--2024"):
            result = runner.invoke(main, ["spell", "Quiet Ward", flag])
            assert result.exit_code == 0
            assert "source: XGE" in result.stdout

    def test_the_flags_are_mutually_exclusive(self, runner, synced):
        result = runner.invoke(main, ["spell", "Test Blast", "--2014", "--2024"])
        assert result.exit_code == 2
        assert "mutually exclusive" in result.output

    def test_a_source_the_edition_excludes_is_rejected(self, runner, synced):
        """Better than reporting no match, which hides the contradiction."""
        result = runner.invoke(main, ["spell", "Test Blast", "--2014", "--source", "XPHB"])
        assert result.exit_code == 2
        assert "other edition" in result.output

    def test_search_drops_the_excluded_handbook(self, runner, synced):
        result = runner.invoke(main, ["search", "Test", "--2014"])
        assert result.exit_code == 0
        assert "\tPHB" in result.output
        assert "\tXPHB" not in result.output

    def test_search_rejects_the_flags_together(self, runner, synced):
        result = runner.invoke(main, ["search", "--2014", "--2024"])
        assert result.exit_code == 2

    def test_search_rejects_a_source_the_edition_excludes(self, runner, synced):
        result = runner.invoke(main, ["search", "--2024", "--source", "PHB"])
        assert result.exit_code == 2


class TestSpellOutputFile:
    def test_writes_a_named_file(self, runner, synced, tmp_path):
        target = tmp_path / "vault"
        result = runner.invoke(main, ["spell", "Quiet Ward", "-o", str(target)])
        assert result.exit_code == 0
        written = target / "Quiet Ward.md"
        assert written.is_file()
        assert written.read_text().startswith("---\n")

    def test_creates_the_directory(self, runner, synced, tmp_path):
        target = tmp_path / "a" / "b"
        runner.invoke(main, ["spell", "Quiet Ward", "-o", str(target)])
        assert (target / "Quiet Ward.md").is_file()

    def test_refuses_to_overwrite_without_force(self, runner, synced, tmp_path):
        runner.invoke(main, ["spell", "Quiet Ward", "-o", str(tmp_path)])
        result = runner.invoke(main, ["spell", "Quiet Ward", "-o", str(tmp_path)])
        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_force_overwrites(self, runner, synced, tmp_path):
        runner.invoke(main, ["spell", "Quiet Ward", "-o", str(tmp_path)])
        result = runner.invoke(main, ["spell", "Quiet Ward", "-o", str(tmp_path), "--force"])
        assert result.exit_code == 0

    def test_unsafe_characters_are_stripped_from_the_filename(
        self, runner, isolated_dirs, tmp_path
    ):
        from fivet.models import Spell
        from fivet.store import Store

        spell = Spell.model_validate({"name": "Bad/Name:Spell", "source": "XPHB", "level": 1})
        Store.build(isolated_dirs["cache"] / sync.INDEX_DB, [spell], meta={"version": VERSION})
        result = runner.invoke(main, ["spell", "Bad/Name:Spell", "-o", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / "Bad_Name_Spell.md").is_file()


class TestSearchCommand:
    def test_lists_matches_as_tab_separated_lines_when_piped(self, runner, synced):
        result = runner.invoke(main, ["search", "Ward"])
        assert result.exit_code == 0
        assert "Quiet Ward\t1\tAbjuration\tXGE" in result.output

    def test_filters_combine(self, runner, synced):
        result = runner.invoke(main, ["search", "Ward", "--level", "1"])
        assert "Quiet Ward" in result.output
        assert "Loud Ward" not in result.output

    def test_filter_by_school_name(self, runner, synced):
        result = runner.invoke(main, ["search", "--school", "evocation"])
        assert "Test Blast" in result.output

    def test_filter_by_class(self, runner, synced):
        result = runner.invoke(main, ["search", "--class", "Druid"])
        assert "Testing Winds" in result.output

    def test_no_results_is_not_an_error(self, runner, synced):
        result = runner.invoke(main, ["search", "Zzzznothing"])
        assert result.exit_code == 0
        assert "No matching spells" in result.stderr

    def test_limit_is_respected(self, runner, synced):
        result = runner.invoke(main, ["search", "--limit", "1"])
        assert len(result.output.strip().splitlines()) == 1


class TestSourcesCommand:
    def test_lists_sources_with_counts(self, runner, synced):
        result = runner.invoke(main, ["sources"])
        assert result.exit_code == 0
        assert "XPHB\t2" in result.output


class TestCacheCommands:
    def test_info_reports_the_version_and_count(self, runner, synced):
        result = runner.invoke(main, ["cache", "info"])
        assert result.exit_code == 0
        assert VERSION in result.output
        assert "Spells" in result.output

    def test_clear_requires_confirmation(self, runner, synced):
        result = runner.invoke(main, ["cache", "clear"], input="n\n")
        assert result.exit_code != 0
        assert synced.exists()

    def test_clear_with_yes_removes_the_cache(self, runner, synced):
        result = runner.invoke(main, ["cache", "clear", "--yes"])
        assert result.exit_code == 0
        assert not synced.exists()

    def test_clear_on_an_empty_cache_is_harmless(self, runner, isolated_dirs):
        import shutil

        shutil.rmtree(isolated_dirs["cache"])
        result = runner.invoke(main, ["cache", "clear", "--yes"])
        assert result.exit_code == 0
        assert "already empty" in result.output
