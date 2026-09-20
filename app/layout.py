"""Page geometry and paragraph styles. The single source of truth.

G4's TOO_LONG check and the milestone 3 renderer must agree exactly on how wide
a line is and which font it is set in, or the gate measures one document and the
renderer produces another. This module is how they agree: it owns every numeric
constant and every ParagraphStyle object, and both sides import them.

The renderer must not construct a ParagraphStyle and must not restate a number
from this file. tests/test_layout_contract.py asserts the renderer's styles are
these objects by identity, and activates automatically once the renderer exists.

Fonts
-----
The PDF uses Helvetica, a base-14 font, and does not embed it. Embedding gives
better visual fidelity but a non-embedded base-14 font is what the widest range
of PDF text extractors handle without surprises, and extraction is what an ATS
does. The DOCX uses Arial with a fallback chain of Helvetica then sans-serif.

Measuring the DOCX against Helvetica metrics is only valid because Arial and
Helvetica are metric-compatible: the two faces have matching advance widths for
the Latin character set, so a line that fits in one fits in the other. If the
DOCX font ever changes to something outside that family, this proxy breaks and
TOO_LONG stops describing the DOCX.
"""

from __future__ import annotations

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph

# Bumped on any change to geometry, fonts, styles, or line limits. The run
# report prints it next to the evidence hash, so a CV produced under different
# geometry is identifiable after the fact.
LAYOUT_VERSION = 1

INCH = 72.0

# ReportLab's own module default is A4. Passing letter explicitly everywhere is
# not redundancy, it is the difference between a 7.0in and a 6.77in frame.
PAGE_SIZE = letter
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE

MARGIN = 0.75 * INCH
MARGINS = {"left": MARGIN, "right": MARGIN, "top": MARGIN, "bottom": MARGIN}

FRAME_WIDTH = PAGE_WIDTH - MARGINS["left"] - MARGINS["right"]
FRAME_HEIGHT = PAGE_HEIGHT - MARGINS["top"] - MARGINS["bottom"]

BODY_FONT = "Helvetica"
BODY_FONT_BOLD = "Helvetica-Bold"
BODY_SIZE = 10.0
BODY_LEADING = 12.0

HEADER_SIZE = 14.0
HEADER_LEADING = 16.5

DOCX_FONT = "Arial"
DOCX_FONT_FALLBACK = ("Helvetica", "sans-serif")

# Spacing, from the spec. PDF in points, DOCX in twips. Twips are twentieths of
# a point, so the two columns are not equal by arithmetic; the spec fixes both
# numbers independently and both are reproduced here rather than derived.
SPACE_BEFORE_ROLE_TITLE_PT = 10.0
SPACE_BEFORE_ROLE_TITLE_TWIPS = 200
SPACE_AFTER_SKILLS_LINE_PT = 5.0
SPACE_AFTER_SKILLS_LINE_TWIPS = 110

# Bullets sit at the frame's left edge. Deep indentation is a common cause of
# mangled extraction, and the glyph plus gap is the only horizontal budget a
# bullet gives up.
BULLET_LEFT_INDENT = 0.0
BULLET_GLYPH = "•"
BULLET_GAP = 4.0
BULLET_GLYPH_WIDTH = stringWidth(BULLET_GLYPH, BODY_FONT, BODY_SIZE)

# Skills category labels are rendered inline as a bold run inside the same
# paragraph, so the label's width is already in the measured markup and no
# column is reserved for it. The constant exists so that a milestone 3 change to
# a two-column skills layout has one place to land.
SKILLS_LABEL_RESERVE = 0.0

_BASE = ParagraphStyle(
    name="base",
    fontName=BODY_FONT,
    fontSize=BODY_SIZE,
    leading=BODY_LEADING,
    alignment=TA_LEFT,
    # Indentation is carried by AVAIL_WIDTH, not by the style. ReportLab's
    # Paragraph.wrap subtracts leftIndent and rightIndent from the width it is
    # given, so an indent set in both places would be subtracted twice and the
    # gate would measure a narrower line than the renderer draws.
    leftIndent=0.0,
    rightIndent=0.0,
    firstLineIndent=0.0,
    spaceBefore=0.0,
    spaceAfter=0.0,
    splitLongWords=0,
    allowWidows=1,
    allowOrphans=1,
)

STYLES: dict[str, ParagraphStyle] = {
    "header": ParagraphStyle(
        name="header",
        parent=_BASE,
        fontName=BODY_FONT_BOLD,
        fontSize=HEADER_SIZE,
        leading=HEADER_LEADING,
    ),
    "role_title": ParagraphStyle(
        name="role_title",
        parent=_BASE,
        fontName=BODY_FONT_BOLD,
        spaceBefore=SPACE_BEFORE_ROLE_TITLE_PT,
    ),
    "summary": ParagraphStyle(name="summary", parent=_BASE),
    "bullet": ParagraphStyle(name="bullet", parent=_BASE),
    "skills_line": ParagraphStyle(
        name="skills_line",
        parent=_BASE,
        spaceAfter=SPACE_AFTER_SKILLS_LINE_PT,
    ),
}

BLOCK_TYPES = tuple(STYLES)

AVAIL_WIDTH: dict[str, float] = {
    "header": FRAME_WIDTH,
    "role_title": FRAME_WIDTH,
    "summary": FRAME_WIDTH,
    "bullet": FRAME_WIDTH - BULLET_LEFT_INDENT - BULLET_GLYPH_WIDTH - BULLET_GAP,
    "skills_line": FRAME_WIDTH - SKILLS_LABEL_RESERVE,
}

# Where the renderer places the glyph and the text of a bullet. Derived here so
# the renderer has no arithmetic of its own to get wrong.
BULLET_GLYPH_X = BULLET_LEFT_INDENT
BULLET_TEXT_X = BULLET_LEFT_INDENT + BULLET_GLYPH_WIDTH + BULLET_GAP

# Only the two limits the spec sets are enforced. A block type absent from this
# mapping is not length-checked.
#
# role_title and header are deliberately absent. The header headline is the
# posting's exact job title and the role title is Yash's real job title. Neither
# is text a model can shorten, so a limit on them would reject a truthful
# document with no available remedy. If a title overflows, the remedy is the
# G5 page-count check and the run report, not a gate that cannot be satisfied.
MAX_LINES: dict[str, int] = {
    "summary": 4,
    "bullet": 3,
}

# Tall enough that wrap never truncates. Line counting, not page fitting.
_MEASURE_HEIGHT = 10_000.0

_XML_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))


def escape_markup(text: str) -> str:
    """Escape plain text for use as ReportLab paragraph markup."""
    for char, entity in _XML_ESCAPES:
        text = text.replace(char, entity)
    return text


def style_for(block_type: str) -> ParagraphStyle:
    try:
        return STYLES[block_type]
    except KeyError:
        raise KeyError(f"unknown block type: {block_type!r}") from None


def available_width(block_type: str) -> float:
    try:
        return AVAIL_WIDTH[block_type]
    except KeyError:
        raise KeyError(f"unknown block type: {block_type!r}") from None


def max_lines(block_type: str) -> int | None:
    """The rendered line limit for a block type, or None when unenforced."""
    if block_type not in STYLES:
        raise KeyError(f"unknown block type: {block_type!r}")
    return MAX_LINES.get(block_type)


def measure_lines(block_type: str, markup: str) -> int:
    """Count the rendered lines a block wraps to.

    The input is final marked-up text, inline bold included, because bold runs
    are wider than regular ones and measuring the stripped string would let a
    bolded bullet overflow by a word.

    This wraps a real Paragraph in the block's real style rather than adding up
    stringWidth calls, so ReportLab's own word-breaking decides where lines end.
    A hand-written wrapper would be a second implementation of line breaking and
    would disagree with the renderer at exactly the boundary cases that matter.
    """
    style = style_for(block_type)
    paragraph = Paragraph(markup, style)
    paragraph.wrap(available_width(block_type), _MEASURE_HEIGHT)
    lines = paragraph.blPara.lines
    return len(lines)
