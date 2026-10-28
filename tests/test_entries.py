"""Tests for the entries tree renderer.

Fixtures are hand-written structures matching the shapes confirmed in the real
data (docs/DESIGN.md section 6.2); no spell text is copied from upstream.
"""

import pytest

from fivet.render.entries import render_block_list, render_blocks
from fivet.render.tags import LinkStyle


class TestStrings:
    def test_a_string_is_a_paragraph(self):
        assert render_blocks(["Hello there."]) == "Hello there."

    def test_paragraphs_are_blank_line_separated(self):
        assert render_blocks(["One.", "Two."]) == "One.\n\nTwo."

    def test_markup_inside_strings_is_rendered(self):
        assert render_blocks(["Takes {@damage 8d6} fire damage."]) == "Takes 8d6 fire damage."

    def test_link_style_is_threaded_through(self):
        entries = ["Target is {@condition Frightened|XPHB}."]
        assert render_blocks(entries, links=LinkStyle.PLAIN) == "Target is Frightened."
        assert render_blocks(entries) == "Target is [[Frightened]]."

    def test_a_bare_string_is_accepted(self):
        assert render_blocks("Just text.") == "Just text."

    @pytest.mark.parametrize("value", [[], None, [""], [None]])
    def test_empty_inputs_render_to_nothing(self, value):
        assert render_blocks(value) == ""


class TestNamedEntries:
    def test_a_named_entries_block_becomes_a_heading(self):
        entry = {
            "type": "entries",
            "name": "Using a Higher-Level Spell Slot",
            "entries": ["The damage increases."],
        }
        assert render_blocks([entry]) == (
            "## Using a Higher-Level Spell Slot\n\nThe damage increases."
        )

    def test_base_level_is_configurable(self):
        entry = {"type": "entries", "name": "Effect", "entries": ["Text."]}
        assert render_blocks([entry], base_level=3) == "### Effect\n\nText."

    def test_nesting_increases_the_heading_level(self):
        entry = {
            "type": "entries",
            "name": "Outer",
            "entries": [{"type": "entries", "name": "Inner", "entries": ["Text."]}],
        }
        assert render_blocks([entry]) == "## Outer\n\n### Inner\n\nText."

    def test_beyond_h6_a_name_becomes_a_bold_lead_in(self):
        """There is no h7, so deep names fold into the paragraph instead."""
        entry = {"type": "entries", "name": "Deep", "entries": ["Text."]}
        assert render_blocks([entry], base_level=7) == "**Deep.** Text."

    def test_an_unnamed_entries_block_just_contributes_its_children(self):
        entry = {"type": "entries", "entries": ["One.", "Two."]}
        assert render_blocks([entry]) == "One.\n\nTwo."

    def test_markup_in_a_name_is_rendered(self):
        entry = {"type": "entries", "name": "See {@i this}", "entries": ["Text."]}
        assert render_blocks([entry]) == "## See *this*\n\nText."


class TestLists:
    def test_plain_string_items_become_bullets(self):
        entry = {"type": "list", "items": ["First", "Second"]}
        assert render_blocks([entry]) == "- First\n- Second"

    def test_named_items_get_a_bold_lead_in(self):
        """This is upstream's hanging list style, where the name runs inline."""
        entry = {
            "type": "list",
            "style": "list-hang-notitle",
            "items": [{"type": "item", "name": "Fire", "entries": ["It burns."]}],
        }
        assert render_blocks([entry]) == "- **Fire.** It burns."

    def test_item_with_a_single_entry_key(self):
        entry = {"type": "list", "items": [{"type": "item", "name": "Cold", "entry": "It chills."}]}
        assert render_blocks([entry]) == "- **Cold.** It chills."

    def test_multi_paragraph_item_indents_its_continuation(self):
        entry = {
            "type": "list",
            "items": [{"type": "item", "name": "Fire", "entries": ["It burns.", "Badly."]}],
        }
        assert render_blocks([entry]) == "- **Fire.** It burns.\n\n  Badly."

    def test_markup_inside_items_is_rendered(self):
        entry = {"type": "list", "items": ["Deals {@damage 1d6} damage"]}
        assert render_blocks([entry]) == "- Deals 1d6 damage"

    def test_empty_list_renders_to_nothing(self):
        assert render_blocks([{"type": "list", "items": []}]) == ""


class TestTables:
    def test_basic_table_is_valid_gfm(self):
        entry = {
            "type": "table",
            "colLabels": ["Roll", "Result"],
            "rows": [["1", "Acid"], ["2", "Cold"]],
        }
        assert render_blocks([entry]) == (
            "| Roll | Result |\n| --- | --- |\n| 1 | Acid |\n| 2 | Cold |"
        )

    def test_caption_becomes_a_bold_line_above(self):
        """GFM has no caption syntax, so it is promoted to a heading-ish line."""
        entry = {
            "type": "table",
            "caption": "Damage Type",
            "colLabels": ["Roll"],
            "rows": [["1"]],
        }
        assert render_blocks([entry]) == "**Damage Type**\n\n| Roll |\n| --- |\n| 1 |"

    def test_markup_in_column_labels_is_rendered(self):
        entry = {
            "type": "table",
            "colLabels": ["{@dice d8}", "Damage Type"],
            "rows": [["1", "Acid"]],
        }
        assert render_blocks([entry]).splitlines()[0] == "| d8 | Damage Type |"

    def test_rollable_cells_with_an_exact_value(self):
        """The real table path in spell data uses cell objects, not plain strings."""
        entry = {
            "type": "table",
            "colLabels": ["Roll", "Result"],
            "rows": [[{"type": "cell", "roll": {"exact": 1}}, "Acid"]],
        }
        assert render_blocks([entry]).splitlines()[-1] == "| 1 | Acid |"

    def test_rollable_cells_with_a_range(self):
        entry = {
            "type": "table",
            "colLabels": ["Roll"],
            "rows": [[{"type": "cell", "roll": {"min": 2, "max": 5}}]],
        }
        assert render_blocks([entry]).splitlines()[-1] == "| 2-5 |"

    def test_padded_rolls_keep_their_leading_zero(self):
        entry = {
            "type": "table",
            "colLabels": ["Roll"],
            "rows": [[{"type": "cell", "roll": {"exact": 1, "pad": True}}]],
        }
        assert render_blocks([entry]).splitlines()[-1] == "| 01 |"

    def test_open_ended_bounds_read_as_or_lower_and_or_higher(self):
        entry = {
            "type": "table",
            "colLabels": ["Roll"],
            "rows": [
                [{"type": "cell", "roll": {"min": -100_000_000, "max": 20}}],
                [{"type": "cell", "roll": {"min": 99, "max": 100_000_000}}],
            ],
        }
        lines = render_blocks([entry]).splitlines()
        assert lines[-2] == "| 20 or lower |"
        assert lines[-1] == "| 99 or higher |"

    def test_cell_with_an_entry_instead_of_a_roll(self):
        entry = {
            "type": "table",
            "colLabels": ["Result"],
            "rows": [[{"type": "cell", "entry": "Deals {@damage 1d6}"}]],
        }
        assert render_blocks([entry]).splitlines()[-1] == "| Deals 1d6 |"

    def test_pipes_in_cell_text_are_escaped(self):
        """An unescaped pipe would break the table structure."""
        entry = {"type": "table", "colLabels": ["X"], "rows": [["a|b"]]}
        assert render_blocks([entry]).splitlines()[-1] == r"| a\|b |"

    def test_piped_wikilink_in_a_cell_is_escaped(self):
        """A wikilink with display text contains a pipe, which would split the row.

        This is the hardest real interaction between the tag layer and tables:
        {@creature animated object (tiny)|phb|Tiny} becomes a piped wikilink
        that must not be read as a cell boundary.
        """
        entry = {
            "type": "table",
            "colLabels": ["Size"],
            "rows": [["{@creature animated object (tiny)|phb|Tiny}"]],
        }
        assert render_blocks([entry]).splitlines()[-1] == (r"| [[animated object (tiny)\|Tiny]] |")

    def test_short_rows_are_padded_to_the_column_count(self):
        entry = {"type": "table", "colLabels": ["A", "B"], "rows": [["only"]]}
        assert render_blocks([entry]).splitlines()[-1] == "| only |  |"

    def test_table_without_labels_still_gets_a_header_row(self):
        entry = {"type": "table", "rows": [["a", "b"]]}
        lines = render_blocks([entry]).splitlines()
        assert lines[0] == "|  |  |"
        assert lines[1] == "| --- | --- |"


class TestInsetAndQuote:
    def test_inset_becomes_a_blockquote(self):
        entry = {"type": "inset", "name": "A Note", "entries": ["Be careful."]}
        assert render_blocks([entry]) == "> **A Note**\n>\n> Be careful."

    def test_unnamed_inset(self):
        entry = {"type": "inset", "entries": ["Be careful."]}
        assert render_blocks([entry]) == "> Be careful."

    def test_quote_attributes_its_source(self):
        entry = {"type": "quote", "entries": ["A saying."], "by": "Someone"}
        assert render_blocks([entry]) == f"> A saying.\n>\n> {chr(0x2014)} Someone"


class TestUnknownTypes:
    def test_unknown_container_still_yields_its_children(self):
        """Dropping content silently is worse than rendering it without its wrapper."""
        entry = {"type": "somethingNew", "entries": ["Kept."]}
        assert render_blocks([entry]) == "Kept."

    def test_unknown_container_with_a_single_entry(self):
        entry = {"type": "somethingNew", "entry": "Kept."}
        assert render_blocks([entry]) == "Kept."

    def test_unknown_leaf_is_skipped(self):
        assert render_blocks([{"type": "image", "href": {"path": "x.webp"}}]) == ""


class TestBlockList:
    def test_returns_blocks_separately(self):
        entries = ["One.", "Two."]
        assert render_block_list(entries) == ["One.", "Two."]
