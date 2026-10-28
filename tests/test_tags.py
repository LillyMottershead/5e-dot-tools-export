"""Tests for the {@tag} markup layer.

Fixtures are hand-written markup, not copied spell text, per docs/DESIGN.md
section 2. Expected values follow upstream's `_getStripped` semantics.
"""

import pytest

from fivet.render import tags
from fivet.render.tags import LinkStyle


class TestSplitByTags:
    def test_plain_text_is_one_segment(self):
        assert tags.split_by_tags("hello world") == ["hello world"]

    def test_separates_literal_and_tag_segments(self):
        assert tags.split_by_tags("a {@b bold} c") == ["a ", "{@b bold}", " c"]

    def test_brace_not_followed_by_at_is_literal(self):
        assert tags.split_by_tags("a {not a tag} b") == ["a {not a tag} b"]

    def test_nested_tag_stays_inside_its_parent(self):
        """Spell data contains a nested tag, so this is a real case, not a hypothetical."""
        result = tags.split_by_tags("x {@note see {@filter these|bestiary|type=beast} now} y")
        assert result == [
            "x ",
            "{@note see {@filter these|bestiary|type=beast} now}",
            " y",
        ]

    def test_empty(self):
        assert tags.split_by_tags("") == []


class TestSplitTagByPipe:
    def test_splits_on_pipes(self):
        assert tags.split_tag_by_pipe("a|b|c") == ["a", "b", "c"]

    def test_no_pipes(self):
        assert tags.split_tag_by_pipe("alone") == ["alone"]

    def test_empty_middle_parts_are_preserved(self):
        """{@chance 25|||yes|no} relies on empty parts holding their positions."""
        assert tags.split_tag_by_pipe("25|||yes|no") == ["25", "", "", "yes", "no"]

    def test_pipe_inside_a_nested_tag_is_not_a_separator(self):
        assert tags.split_tag_by_pipe("see {@spell fireball|xphb} now|second") == [
            "see {@spell fireball|xphb} now",
            "second",
        ]

    def test_escaped_pipe_is_literal(self):
        assert tags.split_tag_by_pipe(r"a\|b|c") == [r"a\|b", "c"]


class TestStyleTags:
    @pytest.mark.parametrize(
        ("markup", "expected"),
        [
            ("{@b loud}", "**loud**"),
            ("{@bold loud}", "**loud**"),
            ("{@i soft}", "*soft*"),
            ("{@italic soft}", "*soft*"),
            ("{@s gone}", "~~gone~~"),
            ("{@code x}", "`x`"),
        ],
    )
    def test_emphasis(self, markup, expected):
        assert tags.render(markup) == expected

    def test_style_tag_renders_its_contents_first(self):
        assert tags.render("{@i see {@b this}}") == "*see **this***"

    def test_empty_style_tag_produces_nothing(self):
        assert tags.render("{@b }") == ""


class TestDiceTags:
    @pytest.mark.parametrize(
        ("markup", "expected"),
        [
            ("{@damage 8d6}", "8d6"),
            ("{@dice 4d10}", "4d10"),
            ("{@dice d20}", "d20"),
            ("{@damage 2d6 + 3}", "2d6 + 3"),
        ],
    )
    def test_plain_dice(self, markup, expected):
        assert tags.render(markup) == expected

    def test_display_text_overrides_the_roll(self):
        assert tags.render("{@dice 1d6|one die}") == "one die"

    def test_semicolons_become_slashes(self):
        """Upstream renders alternative rolls as 1d6/1d8, not 1d6;1d8."""
        assert tags.render("{@damage 1d6;1d8}") == "1d6/1d8"

    def test_prompt_number_becomes_a_placeholder_glyph(self):
        markup = "{@dice #$prompt_number,title=Enter a level$#d6}"
        assert tags.render(markup) == "(\U0001d45b)d6"


class TestD20Tags:
    @pytest.mark.parametrize(
        ("markup", "expected"),
        [
            ("{@hit 8}", "+8"),
            ("{@hit +8}", "+8"),
            ("{@hit -2}", "-2"),
            ("{@d20 0}", "+0"),
            ("{@d20 8}", "+8"),
        ],
    )
    def test_modifiers_are_signed(self, markup, expected):
        assert tags.render(markup) == expected

    def test_non_numeric_passes_through(self):
        assert tags.render("{@hit your proficiency bonus}") == "your proficiency bonus"


class TestScalingTags:
    def test_renders_the_step_not_the_base(self):
        """The surrounding sentence is about the per-level increase.

        Rendering the base here would overstate the scaling eightfold, which is
        the bug this test exists to prevent.
        """
        assert tags.render("{@scaledamage 8d6|3-9|1d6}") == "1d6"

    def test_scaledice_behaves_the_same(self):
        assert tags.render("{@scaledice 2d8|1-9|2d8}") == "2d8"

    def test_flat_numeric_step(self):
        assert tags.render("{@scaledice 70|6-9|10}") == "10"

    def test_display_text_wins(self):
        assert tags.render("{@scaledamage 8d6|3-9|1d6||extra fire}") == "extra fire"


class TestDcAndChance:
    def test_dc_gains_its_prefix(self):
        assert tags.render("{@dc 20}") == "DC 20"

    def test_dc_display_text(self):
        assert tags.render("{@dc 20|twenty}") == "DC twenty"

    def test_chance_spells_out_percent(self):
        assert tags.render("{@chance 25}") == "25 percent"

    def test_chance_ignores_trailing_success_and_failure_text(self):
        """The success and failure strings are rollbox flavor, not prose."""
        assert tags.render("{@chance 25|||Capsizes!|No effect}") == "25 percent"

    def test_chance_display_text_wins(self):
        assert tags.render("{@chance 25|one in four}") == "one in four"

    def test_spell_save_helpers(self):
        assert tags.render("{@dcYourSpellSave}") == "your spell save DC"
        assert tags.render("{@hitYourSpellAttack}") == "your spell attack modifier"

    def test_recharge(self):
        assert tags.render("{@recharge 4}") == "(Recharge 4\u20136)"
        assert tags.render("{@recharge 6}") == "(Recharge 6)"


class TestFirstArgTags:
    @pytest.mark.parametrize(
        ("markup", "expected"),
        [
            ("{@filter any beast|bestiary|type=beast|miscellaneous=!swarm}", "any beast"),
            ("{@book Monster Manual|XMM}", "Monster Manual"),
            ("{@book mounted combat|XPHB|1|Mounted Combat}", "mounted combat"),
            ("{@quickref difficult terrain||3}", "difficult terrain"),
            ("{@quickref Cover||3||total cover}", "total cover"),
        ],
    )
    def test_navigation_payloads_degrade_to_their_label(self, markup, expected):
        assert tags.render(markup) == expected


class TestReferenceTagsWikilink:
    def test_name_only(self):
        assert tags.render("{@condition Frightened}") == "[[Frightened]]"

    def test_name_and_source(self):
        assert tags.render("{@condition Frightened|XPHB}") == "[[Frightened]]"

    def test_display_text_uses_the_piped_form(self):
        """The link target stays canonical so it resolves in a vault."""
        assert tags.render("{@item Holy Water (flask)|phb|holy water}") == (
            "[[Holy Water (flask)|holy water]]"
        )

    def test_display_text_equal_to_name_needs_no_pipe(self):
        assert tags.render("{@spell Fireball|XPHB|Fireball}") == "[[Fireball]]"

    def test_bracketed_qualifier_is_stripped_from_the_target(self):
        assert tags.render("{@variantrule Sphere [Area of Effect]|XPHB|Sphere}") == "[[Sphere]]"

    def test_bare_bracketed_name_is_stripped_too(self):
        """No such case exists upstream today; this guards against one appearing."""
        assert tags.render("{@variantrule Emanation [Area of Effect]|XPHB}") == "[[Emanation]]"


class TestReferenceTagsPlain:
    @pytest.mark.parametrize(
        ("markup", "expected"),
        [
            ("{@condition Frightened|XPHB}", "Frightened"),
            ("{@variantrule Sphere [Area of Effect]|XPHB|Sphere}", "Sphere"),
            ("{@item Holy Water (flask)|phb|holy water}", "holy water"),
            ("{@skill Arcana|XPHB}", "Arcana"),
            ("{@sense darkvision}", "darkvision"),
        ],
    )
    def test_strips_to_display_text(self, markup, expected):
        assert tags.render(markup, links=LinkStyle.PLAIN) == expected

    def test_strip_helper_matches_plain_mode(self):
        assert tags.strip_tags("{@condition Frightened|XPHB}") == "Frightened"


class TestReferenceTagsUrl:
    def test_builds_a_hash_url(self):
        assert tags.render("{@spell Fireball|XPHB}", links=LinkStyle.URL) == (
            "[Fireball](https://5e.tools/spells.html#fireball_xphb)"
        )

    def test_spaces_are_percent_encoded(self):
        result = tags.render("{@condition Heavily Obscured|XPHB}", links=LinkStyle.URL)
        assert result == (
            "[Heavily Obscured](https://5e.tools/conditionsdiseases.html#heavily%20obscured_xphb)"
        )

    def test_display_text_is_the_link_label(self):
        result = tags.render("{@item Holy Water (flask)|phb|holy water}", links=LinkStyle.URL)
        assert result == "[holy water](https://5e.tools/items.html#holy%20water%20(flask)_phb)"

    def test_missing_source_degrades_to_plain_text(self):
        """A guessed source yields a link that silently 404s, so do not guess."""
        assert tags.render("{@condition Frightened}", links=LinkStyle.URL) == "Frightened"

    def test_tag_without_a_page_degrades_to_plain_text(self):
        assert tags.render("{@skill Arcana|XPHB}", links=LinkStyle.URL) == "Arcana"


class TestNesting:
    def test_the_real_nested_case_from_spell_data(self):
        markup = "{@note Additional {@filter animal form choices|bestiary|type=beast} exist}"
        assert tags.render(markup) == "*Additional animal form choices exist*"

    def test_recursion_is_bounded(self):
        markup = "{@i " * 20 + "deep" + "}" * 20
        assert "deep" in tags.render(markup)


class TestUnknownAndEdgeCases:
    def test_unknown_tag_degrades_to_its_first_argument(self):
        """An unrecognized tag must read as prose, never leak markup into notes."""
        assert tags.render("{@invented something|extra}") == "something"

    def test_unknown_tag_does_not_raise(self):
        assert tags.render("{@totallyNew}") == ""

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_input_passes_through(self, value):
        assert tags.render(value) == value

    def test_text_without_tags_is_unchanged(self):
        text = "A bright streak flashes to a point you choose."
        assert tags.render(text) == text

    def test_literal_braces_survive(self):
        assert tags.render("use {braces} freely") == "use {braces} freely"
