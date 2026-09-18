"""The bucket table. Every code, pinned to how it behaves.

This is a literal table, not a derivation. That is the entire point: moving a
code between buckets requires editing this file, so a truth gate cannot be
downgraded to advisory as a side effect of a refactor somewhere else. A test
asserts the table and the registry in app.errors agree in both directions, so
neither a new code nor a changed one can slip through unlisted.

Columns: bucket, severity, retries.

`retries` is None when the code draws on its bucket's budget from policy, and
an explicit number when the code overrides it. Zero means no retry at all.
"""

from __future__ import annotations

TRUTH = "truth"
STYLE = "style"
STRUCTURE = "structure"

REJECT = "reject"
HOLD = "hold"
ADVISORY = "advisory"

#: code -> (bucket, severity, retries)
TABLE: dict[str, tuple[str, str, int | None]] = {
    # G0 text hygiene. Zero retries: a homoglyph is not a phrasing problem.
    "INVISIBLE_CHAR": (TRUTH, REJECT, 0),
    "MIXED_SCRIPT": (TRUTH, REJECT, 0),
    "NON_LATIN_SCRIPT": (TRUTH, REJECT, 0),
    # G1 technology.
    "TECH_UNCONFIRMED": (TRUTH, REJECT, None),
    "TECH_DENIED": (TRUTH, REJECT, None),
    "JD_TERM_NOT_IN_EVIDENCE": (TRUTH, REJECT, None),
    "UNKNOWN_TERM": (TRUTH, HOLD, None),
    # G2 scope.
    "SCOPE_DEPTH": (TRUTH, REJECT, None),
    "SCOPE_CONTEXT": (TRUTH, REJECT, None),
    "SCOPE_SERVICE": (TRUTH, REJECT, None),
    "SCOPE_EXPOSURE_IN_BULLET": (TRUTH, REJECT, None),
    "SCOPE_COHABITATION": (TRUTH, REJECT, None),
    # G3 numbers.
    "NUMBER_UNSUPPORTED": (TRUTH, REJECT, None),
    "VAGUE_METRIC": (TRUTH, REJECT, None),
    "VERSION_UNSUPPORTED": (TRUTH, REJECT, None),
    "CITATION_MISSING": (TRUTH, REJECT, None),
    "CITATION_UNKNOWN": (TRUTH, REJECT, None),
    "UNCITED_NUMBER": (TRUTH, REJECT, None),
    # G4 structure and style.
    "BULLET_COUNT": (STRUCTURE, REJECT, None),
    "BANNED_VERB": (STYLE, REJECT, None),
    "WEAK_OPENING": (STYLE, REJECT, None),
    "OPENING_VERB_UNLISTED": (STYLE, ADVISORY, None),
    "UNVERIFIABLE_LABEL": (STYLE, REJECT, 1),
    "TITLE_CLAIM_UNVERIFIED": (STYLE, ADVISORY, None),
    "EM_DASH": (TRUTH, REJECT, None),
    "CLIENT_NAME": (TRUTH, REJECT, None),
    "JD_COPY": (TRUTH, REJECT, None),
    "TOO_LONG": (STYLE, REJECT, None),
    "SKILLS_EXPOSURE": (TRUTH, REJECT, None),
    "SKILLS_PROFICIENCY": (TRUTH, REJECT, None),
    # G5 round trip.
    "ROUNDTRIP_TEXT_MISSING": (STRUCTURE, REJECT, None),
    "ROUNDTRIP_ORDER": (STRUCTURE, REJECT, None),
    "ROUNDTRIP_STRUCTURE": (STRUCTURE, REJECT, None),
    "PAGE_COUNT_EXCEEDED": (STRUCTURE, REJECT, None),
    # Schema.
    "SCHEMA_INVALID": (STRUCTURE, REJECT, None),
}

#: Codes that must never block rendering. Listed separately so the intent is
#: readable without decoding the tuples.
ADVISORY_ONLY = frozenset(code for code, (_, severity, _r) in TABLE.items() if severity == ADVISORY)

#: Codes that drop the block once their budget is spent.
TRUTH_CODES = frozenset(code for code, (bucket, _s, _r) in TABLE.items() if bucket == TRUTH)
STYLE_CODES = frozenset(code for code, (bucket, _s, _r) in TABLE.items() if bucket == STYLE)


def retries_for(code: str, policy_limits: dict[str, int]) -> int:
    """The retry budget for a code: its own override, else its bucket's."""
    bucket, _severity, override = TABLE[code]
    if override is not None:
        return override
    return int(policy_limits.get(bucket, 0))
