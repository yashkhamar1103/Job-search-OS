"""The layout contract.

app/layout.py is the single source of truth for geometry and paragraph styles.
G4 measures with it and the milestone 3 renderer must draw with it. These tests
are what stops the two drifting apart.

The golden line counts are pinned on purpose. A geometry change makes them fail,
which forces a deliberate decision and a LAYOUT_VERSION bump rather than a
silent change in what fits on a line.
"""

from __future__ import annotations

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle

from app import layout


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_page_size_is_letter_not_reportlabs_a4_default():
    """ReportLab's own module default is A4. The difference between a 7.0in and
    a 6.77in frame is a word per line."""
    assert layout.PAGE_SIZE == letter
    assert layout.PAGE_WIDTH == pytest.approx(612.0)
    assert layout.PAGE_HEIGHT == pytest.approx(792.0)


def test_margins_and_frame_width():
    assert layout.MARGIN == pytest.approx(54.0)
    assert layout.FRAME_WIDTH == pytest.approx(504.0)


def test_body_font_is_helvetica_at_ten_point():
    assert layout.BODY_FONT == "Helvetica"
    assert layout.BODY_SIZE == pytest.approx(10.0)


def test_docx_font_is_metric_compatible_with_the_pdf_font():
    """The DOCX proxy is only valid because Arial and Helvetica share advance
    widths. If the DOCX font leaves that family, TOO_LONG stops describing the
    DOCX and this test is the tripwire."""
    assert layout.DOCX_FONT == "Arial"
    assert "Helvetica" in layout.DOCX_FONT_FALLBACK


def test_spacing_matches_the_spec():
    assert layout.SPACE_BEFORE_ROLE_TITLE_PT == pytest.approx(10.0)
    assert layout.SPACE_BEFORE_ROLE_TITLE_TWIPS == 200
    assert layout.SPACE_AFTER_SKILLS_LINE_PT == pytest.approx(5.0)
    assert layout.SPACE_AFTER_SKILLS_LINE_TWIPS == 110


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_every_block_type_has_a_style_and_a_width():
    for block_type in layout.BLOCK_TYPES:
        assert isinstance(layout.style_for(block_type), ParagraphStyle)
        assert layout.available_width(block_type) > 0


def test_styles_carry_no_indent_because_width_carries_it():
    """ReportLab's Paragraph.wrap subtracts leftIndent from the width it is
    given. An indent set in both places would be subtracted twice, and the gate
    would measure a narrower line than the renderer draws."""
    for block_type in layout.BLOCK_TYPES:
        style = layout.style_for(block_type)
        assert style.leftIndent == 0
        assert style.rightIndent == 0
        assert style.firstLineIndent == 0


def test_bullet_width_accounts_for_the_glyph_and_gap():
    expected = (
        layout.FRAME_WIDTH
        - layout.BULLET_LEFT_INDENT
        - layout.BULLET_GLYPH_WIDTH
        - layout.BULLET_GAP
    )
    assert layout.available_width("bullet") == pytest.approx(expected)
    assert layout.available_width("bullet") < layout.FRAME_WIDTH


def test_bullet_text_origin_is_derived_here_not_in_the_renderer():
    assert layout.BULLET_TEXT_X == pytest.approx(
        layout.BULLET_LEFT_INDENT + layout.BULLET_GLYPH_WIDTH + layout.BULLET_GAP
    )


def test_only_the_two_specified_limits_are_enforced():
    """The header headline is the posting's exact job title and the role title
    is a real job title. Neither is text a model can shorten, so a limit on them
    would reject a truthful document with no available remedy."""
    assert layout.max_lines("summary") == 4
    assert layout.max_lines("bullet") == 3
    assert layout.max_lines("role_title") is None
    assert layout.max_lines("header") is None
    assert layout.max_lines("skills_line") is None


def test_an_unknown_block_type_raises_rather_than_defaulting():
    with pytest.raises(KeyError):
        layout.style_for("nope")
    with pytest.raises(KeyError):
        layout.available_width("nope")
    with pytest.raises(KeyError):
        layout.max_lines("nope")


def test_layout_version_is_an_integer_for_the_run_report():
    assert isinstance(layout.LAYOUT_VERSION, int)


# ---------------------------------------------------------------------------
# Golden line counts
# ---------------------------------------------------------------------------

#: Pinned expected line counts. A geometry change shows up here as a diff and
#: forces a deliberate decision.
GOLDEN = [
    ("bullet", "Configured the ingestion path.", 1),
    (
        "bullet",
        "Configured the ingestion path for order events so that downstream consumers "
        "received them within the agreed window.",
        2,
    ),
    (
        "bullet",
        "Configured the ingestion path for order events so that downstream consumers "
        "received them within the agreed window, replacing a nightly batch job that had "
        "run unchanged for three years, had no documented owner, and failed silently "
        "whenever an upstream schema changed.",
        3,
    ),
    (
        "bullet",
        "Configured the ingestion path for order events so that downstream consumers "
        "received them within the agreed window, replacing a nightly batch job that had "
        "run unchanged for three years, had no documented owner, failed silently "
        "whenever an upstream schema changed, and could not be re-run without manual "
        "intervention from two separate teams.",
        4,
    ),
    ("summary", "Backend engineer.", 1),
    (
        "summary",
        "Backend engineer building ingestion and reporting systems, with a bias toward "
        "boring technology and toward leaving a system easier to operate than it was.",
        2,
    ),
    (
        "summary",
        "Backend engineer building ingestion and reporting systems, with a bias toward "
        "boring technology and toward leaving a system easier to operate than it was "
        "found. Comfortable owning a service end to end, from the schema through to the "
        "on-call rota and the runbook that goes with it.",
        3,
    ),
    ("role_title", "Backend Engineer", 1),
    ("skills_line", "Languages: Python", 1),
]


@pytest.mark.parametrize("block_type,text,expected", GOLDEN)
def test_golden_line_counts(block_type, text, expected):
    assert layout.measure_lines(block_type, layout.escape_markup(text)) == expected


def test_markup_special_characters_are_escaped_not_interpreted():
    """An ampersand or angle bracket in a bullet must not be read as markup."""
    assert layout.measure_lines("bullet", layout.escape_markup("R&D <ops> team")) == 1


def test_bold_is_measured_as_wider_than_regular():
    text = "Configured the ingestion path for order events across every region in the fleet"
    plain = layout.measure_lines("bullet", layout.escape_markup(text))
    bold = layout.measure_lines("bullet", f"<b>{layout.escape_markup(text)}</b>")
    assert bold >= plain


# ---------------------------------------------------------------------------
# The renderer contract. Activates in milestone 3.
# ---------------------------------------------------------------------------


def test_the_renderer_uses_these_exact_style_objects():
    """Identity, not equality.

    A renderer that builds its own ParagraphStyle with the same numbers passes
    an equality check and still drifts the moment one side is edited. Skipped
    until app.render exists, and enforced automatically from then on.
    """
    render = pytest.importorskip("app.render", reason="milestone 3 has not landed yet")

    styles = getattr(render, "STYLES", None)
    assert styles is not None, "app.render must expose the shared STYLES registry"
    for block_type, style in layout.STYLES.items():
        assert styles[block_type] is style, (
            f"app.render rebuilt the {block_type} style instead of importing it"
        )


def test_the_renderer_restates_no_geometry_constant():
    """Milestone 3 must import the numbers, not copy them."""
    render = pytest.importorskip("app.render", reason="milestone 3 has not landed yet")

    source = __import__("inspect").getsource(render)
    for forbidden in ("letter", "0.75 * ", "504", "612", "792"):
        assert forbidden not in source, (
            f"app.render restates {forbidden!r}; import it from app.layout instead"
        )
