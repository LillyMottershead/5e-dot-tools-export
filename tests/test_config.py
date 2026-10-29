"""Tests for settings loading and source ranking."""

import pytest
from pydantic import ValidationError

from fivet import config
from fivet.config import Edition, Settings
from fivet.render.tags import LinkStyle


class TestPaths:
    def test_env_overrides_are_respected(self, isolated_dirs):
        assert config.cache_dir() == isolated_dirs["cache"]
        assert config.config_dir() == isolated_dirs["config"]

    def test_derived_paths(self, isolated_dirs):
        assert config.config_path() == isolated_dirs["config"] / "config.toml"
        assert config.template_dir() == isolated_dirs["config"] / "templates"

    def test_defaults_to_platform_dirs_without_an_override(self, monkeypatch):
        monkeypatch.delenv("FIVET_CACHE_DIR", raising=False)
        monkeypatch.delenv("FIVET_CONFIG_DIR", raising=False)
        assert "5et" in str(config.cache_dir())
        assert "5et" in str(config.config_dir())


class TestDefaults:
    def test_defaults_match_the_documented_design(self):
        settings = Settings()
        assert settings.links is LinkStyle.WIKILINK
        assert settings.template == "obsidian"
        assert settings.fuzzy_cutoff == 80
        assert settings.output_dir is None

    def test_2024_sources_outrank_2014_by_default(self):
        settings = Settings()
        assert settings.source_priority[0] == "XPHB"
        assert settings.source_priority[1] == "PHB"

    def test_missing_config_file_yields_defaults(self, isolated_dirs):
        assert config.load_settings() == Settings()


class TestLoading:
    def test_reads_values_from_toml(self, write_config):
        write_config(
            "\n".join(
                [
                    'links = "plain"',
                    'template = "compact"',
                    "fuzzy_cutoff = 90",
                    'source_priority = ["PHB", "XPHB"]',
                ]
            )
        )
        settings = config.load_settings()
        assert settings.links is LinkStyle.PLAIN
        assert settings.template == "compact"
        assert settings.fuzzy_cutoff == 90
        assert settings.source_priority == ["PHB", "XPHB"]

    def test_output_dir_is_expanded(self, write_config):
        write_config('output_dir = "~/vault/Spells"')
        settings = config.load_settings()
        assert "~" not in str(settings.output_dir)
        assert str(settings.output_dir).endswith("vault/Spells")

    def test_an_unknown_key_is_an_error_not_a_silent_no_op(self, write_config):
        """A typo in a hand-written config should be heard, unlike upstream data."""
        write_config('linkz = "plain"')
        with pytest.raises(ValidationError):
            config.load_settings()

    def test_an_invalid_link_style_is_rejected(self, write_config):
        write_config('links = "hyperlink"')
        with pytest.raises(ValidationError):
            config.load_settings()

    @pytest.mark.parametrize("value", [-1, 101])
    def test_fuzzy_cutoff_is_bounded(self, write_config, value):
        write_config(f"fuzzy_cutoff = {value}")
        with pytest.raises(ValidationError):
            config.load_settings()


class TestSourceRank:
    def test_listed_sources_rank_by_position(self):
        settings = Settings()
        assert settings.source_rank("XPHB") < settings.source_rank("PHB")
        assert settings.source_rank("PHB") < settings.source_rank("XGE")

    def test_rank_is_case_insensitive(self):
        settings = Settings()
        assert settings.source_rank("xphb") == settings.source_rank("XPHB")

    def test_unlisted_sources_sort_last_and_deterministically(self):
        """Resolution must not depend on dict ordering."""
        settings = Settings()
        assert settings.source_rank("ZZZ") > settings.source_rank("AitFR-AVT")
        assert settings.source_rank("AAAA") < settings.source_rank("BBBB")

    def test_a_custom_priority_inverts_the_choice(self):
        settings = Settings(source_priority=["PHB", "XPHB"])
        assert settings.source_rank("PHB") < settings.source_rank("XPHB")


class TestEdition:
    def test_each_edition_names_its_own_handbook(self):
        assert Edition.LEGACY.phb == "PHB"
        assert Edition.REVISED.phb == "XPHB"

    def test_each_edition_excludes_the_other_handbook(self):
        """An edition rules out one book, rather than restricting to one."""
        assert Edition.LEGACY.excluded_source == "XPHB"
        assert Edition.REVISED.excluded_source == "PHB"

    def test_the_values_are_the_flag_names(self):
        assert Edition("2014") is Edition.LEGACY
        assert Edition("2024") is Edition.REVISED

    def test_no_supplement_is_excluded_by_either_edition(self):
        """Only the two handbooks are edition-specific; see config.Edition."""
        excluded = {edition.excluded_source for edition in Edition}
        supplements = [s for s in config.DEFAULT_SOURCE_PRIORITY if s not in {"PHB", "XPHB"}]
        assert excluded == {"PHB", "XPHB"}
        assert not excluded.intersection(supplements)
