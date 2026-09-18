"""G0, the text hygiene gate. Runs before every other gate.

Three checks, all truth bucket, all zero retries, none ever auto-corrected.

Auto-correction is the tempting option and the wrong one. Silently stripping an
invisible character or folding a homoglyph would produce clean output and erase
the only evidence that something put the character there. The fold in
app.normalise exists so the term is still classified; it does not excuse the
text.

Asymmetric by design:

  Generated text   rejected. Nothing this system produces has any business
                   carrying a Cyrillic a inside an English word.

  Job descriptions  stripped and recorded, never rejected. Yash does not control
                   what a recruiter pasted into a posting, and refusing to read
                   a posting because it contains a stray soft hyphen would make
                   the tool unusable for reasons that are nobody's fault. Terms
                   extracted from a stripped span are flagged so the watch list
                   records that they arrived altered.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from app.errors import GateResult, Rejection
from app.gates.context import BlockAnalysis, GateContext
from app.normalise import Token

#: Zero-width, invisible, and bidi control characters.
INVISIBLE_CHARS = frozenset(
    "​‌‍‎‏"  # zero width space through RTL mark
    "⁠"  # word joiner
    "­"  # soft hyphen
    "﻿"  # byte order mark
    "‪‫‬‭‮"  # bidi embedding and override
    "⁦⁧⁨⁩"  # bidi isolates
    "᠎"  # mongolian vowel separator
)

LATIN = "LATIN"
COMMON = "COMMON"

#: Scripts whose letters are legal in generated text. Latin only. Latin Extended
#: accented characters resolve to LATIN here, so they stay legal.
ALLOWED_SCRIPTS = frozenset({LATIN})

_KNOWN_SCRIPTS = frozenset(
    {
        "LATIN", "CYRILLIC", "GREEK", "ARABIC", "HEBREW", "HAN", "HIRAGANA",
        "KATAKANA", "HANGUL", "DEVANAGARI", "THAI", "ARMENIAN", "GEORGIAN",
        "BENGALI", "TAMIL", "TELUGU", "KANNADA", "MALAYALAM", "GUJARATI",
        "GURMUKHI", "ORIYA", "SINHALA", "MYANMAR", "KHMER", "LAO", "TIBETAN",
        "ETHIOPIC", "CHEROKEE", "MONGOLIAN", "SYRIAC", "THAANA", "COPTIC",
    }
)


def script_of(char: str) -> str:
    """The Unicode script a character belongs to, or COMMON.

    Derived from the character's Unicode name, because the standard library has
    no script property. A digit, a space, or a punctuation mark has no script
    name and counts as COMMON, so it never makes a token mixed on its own.
    """
    if not char.isalpha():
        return COMMON
    try:
        name = unicodedata.name(char)
    except ValueError:
        return COMMON
    head = name.split(" ", 1)[0]
    return head if head in _KNOWN_SCRIPTS else COMMON


def scripts_in(text: str) -> frozenset[str]:
    """Every non-COMMON script present in `text`."""
    return frozenset(s for s in (script_of(c) for c in text) if s != COMMON)


@dataclass(frozen=True)
class JDHygiene:
    """What a job description carried, and what was removed from it."""

    text: str
    """The posting with invisible characters removed. Never rejected."""

    invisible_removed: tuple[tuple[int, str], ...] = ()
    """(index in the original, character name) for each stripped character."""

    altered_spans: tuple[tuple[int, int], ...] = field(default_factory=tuple)
    """Ranges in the original text that a strip passed through. A term extracted
    from one of these is flagged as having arrived altered."""

    @property
    def clean(self) -> bool:
        return not self.invisible_removed

    def report_lines(self) -> tuple[str, ...]:
        return tuple(
            f"job description: removed {name} at offset {index}"
            for index, name in self.invisible_removed
        )


def sanitise_jd(text: str) -> JDHygiene:
    """Strip invisible characters from a posting and record what was removed.

    Never rejects. A posting is an input from outside, and the person pasting it
    is not the person this system is checking.
    """
    kept: list[str] = []
    removed: list[tuple[int, str]] = []
    spans: list[tuple[int, int]] = []

    for index, char in enumerate(text):
        if char in INVISIBLE_CHARS:
            try:
                name = unicodedata.name(char)
            except ValueError:
                name = f"U+{ord(char):04X}"
            removed.append((index, name))
            spans.append((max(0, index - 1), min(len(text), index + 2)))
            continue
        kept.append(char)

    return JDHygiene("".join(kept), tuple(removed), tuple(spans))


def check(analysis: BlockAnalysis, ctx: GateContext) -> GateResult:
    """Run G0 over generated text. Rejects; never repairs."""
    rejections: list[Rejection] = []
    rejections.extend(_invisible(analysis))
    rejections.extend(_scripts(analysis))
    return GateResult(tuple(rejections))


def _invisible(analysis: BlockAnalysis):
    text = analysis.block.text
    for index, char in enumerate(text):
        if char not in INVISIBLE_CHARS:
            continue
        try:
            name = unicodedata.name(char)
        except ValueError:
            name = f"U+{ord(char):04X}"
        yield analysis.reject(
            "INVISIBLE_CHAR",
            analysis.span(index, index + 1),
            f"{name} (U+{ord(char):04X}) is invisible and can hide a term from "
            f"every gate that reads tokens",
            character=f"U+{ord(char):04X}",
        )


def _scripts(analysis: BlockAnalysis):
    seen_non_latin: set[int] = set()

    for token in analysis.tokens:
        present = scripts_in(token.raw)
        if len(present) > 1:
            seen_non_latin.add(token.index)
            yield analysis.reject(
                "MIXED_SCRIPT",
                analysis.token_span(token),
                f"{token.raw!r} mixes {', '.join(sorted(present))}, which is how a "
                f"homoglyph is smuggled into an otherwise Latin word",
                scripts=",".join(sorted(present)),
            )

    for token in analysis.tokens:
        foreign = sorted(present for present in scripts_in(token.raw) if present not in ALLOWED_SCRIPTS)
        if not foreign:
            continue
        yield analysis.reject(
            "NON_LATIN_SCRIPT",
            analysis.token_span(token),
            f"{token.raw!r} contains {', '.join(foreign)} letters; Latin Extended "
            f"accented characters remain legal",
            scripts=",".join(foreign),
        )
