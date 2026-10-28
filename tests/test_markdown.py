"""Tests for markdown export.

Frontmatter correctness is checked by parsing it, not by string comparison, so
a template tweak does not fail a test about YAML validity.
"""

import pytest

from fivet.models import Spell
from fivet.render.markdown import (
    TemplateMissingError,
    available_templates,
    build_context,
    render_spell,
    yaml_flow_list,
    yaml_scalar,
)
from fivet.render.tags import LinkStyle


def frontmatter(text: str) -> dict:
    """Parse the frontmatter block with a minimal reader, no yaml dependency."""
    assert text.startswith("---\n")
    _, block, _ = text.split("---\n", 2)
    out = {}
    for line in block.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


class TestYamlScalar:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Fireball", "Fireball"),
            ("V, S, M (a ball of guano)", "V, S, M (a ball of guano)"),
            ("Bigby's Hand", "Bigby's Hand"),
            ("Self (30-foot radius)", "Self (30-foot radius)"),
            (3, "3"),
            (True, "true"),
            (False, "false"),
            (None, '""'),
        ],
    )
    def test_safe_values_are_left_bare(self, value, expected):
        assert yaml_scalar(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            # A rendered wikilink would otherwise start a YAML flow sequence.
            ("[[Concentration]], up to 1 minute", '"[[Concentration]], up to 1 minute"'),
            ("- leading dash", '"- leading dash"'),
            ("key: value", '"key: value"'),
            ("trailing colon:", '"trailing colon:"'),
            ("has # comment", '"has # comment"'),
            ("", '""'),
            (" padded ", '" padded "'),
            ("true", '"true"'),
            ("null", '"null"'),
            ("no", '"no"'),
            ("42", '"42"'),
            ("1.5", '"1.5"'),
        ],
    )
    def test_hazardous_values_are_quoted(self, value, expected):
        assert yaml_scalar(value) == expected

    def test_embedded_quotes_are_escaped(self):
        assert yaml_scalar('a "quoted" word: yes') == '"a \\"quoted\\" word: yes"'

    def test_backslashes_are_escaped(self):
        assert yaml_scalar("a\\b: c") == '"a\\\\b: c"'


class TestYamlFlowList:
    def test_empty_list(self):
        assert yaml_flow_list([]) == "[]"

    def test_simple_items(self):
        assert yaml_flow_list(["Sorcerer", "Wizard"]) == "[Sorcerer, Wizard]"

    def test_hazardous_items_are_quoted(self):
        assert yaml_flow_list(["a, b", "ok"]) == '["a, b", ok]'


class TestContext:
    def test_contains_the_documented_fields(self, raw_spell):
        context = build_context(Spell.model_validate(raw_spell), data_version="v2.39.0")
        for key in [
            "name",
            "level",
            "level_text",
            "school",
            "subtitle",
            "casting_time",
            "range",
            "components",
            "duration",
            "concentration",
            "ritual",
            "classes",
            "source",
            "page",
            "source_page",
            "description_md",
            "higher_levels_md",
            "data_version",
        ]:
            assert key in context

    def test_body_prose_carries_the_link_style(self, raw_spell):
        wikilink = build_context(Spell.model_validate(raw_spell))
        plain = build_context(Spell.model_validate(raw_spell), links=LinkStyle.PLAIN)
        assert "[[burning]]" in wikilink["description_md"]
        assert "burning" in plain["description_md"]
        assert "[[" not in plain["description_md"]

    def test_frontmatter_values_are_plain_regardless_of_link_style(self, raw_cantrip):
        """A wikilink is useless as a property value, and unsafe in YAML."""
        context = build_context(Spell.model_validate(raw_cantrip), links=LinkStyle.WIKILINK)
        assert context["duration"] == "Concentration, up to 1 minute"
        assert "[[" not in context["duration"]

    def test_scaling_renders_the_step(self, raw_spell):
        context = build_context(Spell.model_validate(raw_spell))
        assert "increases by 1d6" in context["higher_levels_md"]

    def test_higher_levels_inline_folds_the_heading_into_a_lead_in(self, raw_spell):
        context = build_context(Spell.model_validate(raw_spell))
        assert context["higher_levels_md"].startswith("## ")
        assert context["higher_levels_inline"].startswith("**Using a Higher-Level Spell Slot.**")

    def test_source_page_omits_a_missing_page(self, raw_spell):
        del raw_spell["page"]
        assert build_context(Spell.model_validate(raw_spell))["source_page"] == "XPHB"

    def test_tags_describe_level_school_and_flags(self, raw_cantrip):
        tags = build_context(Spell.model_validate(raw_cantrip))["tags"]
        assert "spell/level/0" in tags
        assert "spell/school/transmutation" in tags
        assert "spell/concentration" in tags
        assert "spell/ritual" in tags


class TestTemplates:
    def test_three_templates_ship(self):
        assert set(available_templates()) >= {"obsidian", "plain", "compact"}

    def test_unknown_template_lists_the_available_ones(self, raw_spell):
        spell = Spell.model_validate(raw_spell)
        with pytest.raises(TemplateMissingError, match="obsidian"):
            render_spell(spell, template="nonexistent")

    def test_a_user_template_shadows_a_shipped_one(self, tmp_path, raw_spell):
        (tmp_path / "obsidian.md.j2").write_text("custom {{ name }}\n")
        rendered = render_spell(Spell.model_validate(raw_spell), extra_dirs=[tmp_path])
        assert rendered == "custom Test Blast\n"

    def test_a_user_template_can_add_a_new_name(self, tmp_path, raw_spell):
        (tmp_path / "mine.md.j2").write_text("{{ name }} at level {{ level }}\n")
        rendered = render_spell(
            Spell.model_validate(raw_spell), template="mine", extra_dirs=[tmp_path]
        )
        assert rendered == "Test Blast at level 3\n"
        assert "mine" in available_templates(extra_dirs=[tmp_path])


class TestObsidianTemplate:
    def test_frontmatter_is_well_formed(self, raw_spell):
        spell = Spell.model_validate(raw_spell)
        spell.classes = ["Sorcerer", "Wizard"]
        meta = frontmatter(render_spell(spell, data_version="v2.39.0"))
        assert meta["title"] == "Test Blast"
        assert meta["level"] == "3"
        assert meta["school"] == "Evocation"
        assert meta["concentration"] == "false"
        assert meta["classes"] == "[Sorcerer, Wizard]"
        assert meta["source"] == "XPHB p.100"
        assert meta["data_version"] == "v2.39.0"

    def test_a_spell_with_no_class_data_gets_an_empty_list(self, raw_spell):
        meta = frontmatter(render_spell(Spell.model_validate(raw_spell)))
        assert meta["classes"] == "[]"

    def test_data_version_is_omitted_when_unknown(self, raw_spell):
        text = render_spell(Spell.model_validate(raw_spell))
        assert "data_version" not in frontmatter(text)

    def test_body_has_a_title_subtitle_and_prose(self, raw_spell):
        text = render_spell(Spell.model_validate(raw_spell))
        body = text.split("---\n", 2)[2]
        assert body.lstrip().startswith("# Test Blast")
        assert "3rd-level evocation" in body
        assert "## Using a Higher-Level Spell Slot" in body

    def test_concentration_spell_sets_the_flag(self, raw_cantrip):
        text = render_spell(Spell.model_validate(raw_cantrip))
        meta = frontmatter(text)
        assert meta["concentration"] == "true"
        assert meta["ritual"] == "true"

    def test_a_spell_without_higher_levels_has_no_trailing_blank_block(self, raw_cantrip):
        text = render_spell(Spell.model_validate(raw_cantrip))
        assert "\n\n\n" not in text
        assert text.endswith("\n")
        assert not text.endswith("\n\n")

    def test_no_markup_leaks_into_the_output(self, raw_spell):
        assert "{@" not in render_spell(Spell.model_validate(raw_spell))


class TestOtherTemplates:
    def test_plain_lists_the_fields(self, raw_spell):
        text = render_spell(Spell.model_validate(raw_spell), template="plain")
        assert "- Casting Time: 1 action" in text
        assert "- Range: 150 feet" in text
        assert text.startswith("# Test Blast")

    def test_compact_keeps_the_header_on_its_own_line(self, raw_spell):
        text = render_spell(Spell.model_validate(raw_spell), template="compact")
        lines = text.splitlines()
        assert lines[0] == "**Test Blast** (3rd-level evocation)"
        assert lines[1].startswith("1 action | 150 feet |")

    def test_compact_flags_a_ritual(self, raw_cantrip):
        text = render_spell(Spell.model_validate(raw_cantrip), template="compact")
        assert text.splitlines()[0].endswith("[ritual]")

    def test_compact_avoids_an_h2_for_higher_levels(self, raw_spell):
        text = render_spell(Spell.model_validate(raw_spell), template="compact")
        assert "## " not in text
        assert "**Using a Higher-Level Spell Slot.**" in text
