"""Preconditions: does this input still contain what the rule needs?

A rejection test asserts that a gate fires. It does not, on its own, assert that
the input still contains the thing the gate is supposed to fire on. Those are
different claims, and the gap between them is where a test goes quietly green
while checking nothing.

That is not hypothetical here. A cohabitation test used the phrase "Kafka
streams", which longest-first matching reads as the product Kafka Streams. Its
sentence therefore held one confirmed technology and one unconfirmed one, not
the two confirmed technologies under disjoint roles the test claimed to be
about. It passed for years of commits on a cohabitation group of size one, and
only a guard added for an unrelated reason exposed it.

Every predicate here is computed from structural facts or from the raw text,
never from a gate's verdict. Asserting "the gate fired, therefore its input was
present" is circular and would restore exactly the blind spot this module
exists to remove.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.gates import analyse
from app.gates.g0_hygiene import INVISIBLE_CHARS, scripts_in
from app.gates.g4_structure import DOUBLE_HYPHEN, EM_DASH, HORIZONTAL_BAR
from app.models import BULLET, SKILLS_LINE, SUMMARY, Block, Document
from app.normalise import token_texts

_YEARS_RE = re.compile(r"(?i)\b\d+\s*\+?\s*(?:year|yr)s?\b")


class PreconditionError(AssertionError):
    """The input no longer contains what the rule under test needs.

    Raised instead of a plain failure so the message says which half broke: the
    gate, or the example the gate was pointed at.
    """


@dataclass(frozen=True)
class Facts:
    """Structural facts about one block, independent of any gate verdict."""

    block: Block
    analysis: object
    ctx: object

    @property
    def text(self) -> str:
        return self.block.text

    @property
    def folded(self) -> str:
        return " ".join(t.folded for t in self.analysis.tokens)

    @property
    def confirmed_matches(self) -> tuple:
        return tuple(m for m in self.analysis.matches if m.resolution.confirmed)

    @property
    def contextful_matches(self) -> tuple:
        return tuple(m for m in self.confirmed_matches if m.resolution.contexts)

    def confirmed_per_sentence(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for match in self.contextful_matches:
            counts[match.sentence] = counts.get(match.sentence, 0) + 1
        return counts

    def has_phrase(self, phrase: str) -> bool:
        wanted = token_texts(phrase)
        if not wanted:
            return False
        have = tuple(t.folded for t in self.analysis.tokens)
        return any(
            have[i : i + len(wanted)] == wanted
            for i in range(0, max(0, len(have) - len(wanted) + 1))
        )

    def has_any_phrase(self, key: str) -> bool:
        return any(self.has_phrase(p) for p in self.ctx.bundle.policy.list_of(key))


def facts_for(block: Block, ctx) -> Facts:
    return Facts(block, analyse(block, ctx), ctx)


# ---------------------------------------------------------------------------
# One predicate per code. Each answers: is the rule's input present?
# ---------------------------------------------------------------------------


def _taxonomy_match(f: Facts) -> tuple[bool, str]:
    return bool(f.analysis.matches), (
        f"no taxonomy term resolves in {f.text!r}, so there is nothing for the "
        f"technology gate to classify"
    )


def _build_verb_and_technology(f: Facts) -> tuple[bool, str]:
    verbs = tuple(
        t for t in f.analysis.tokens
        if f.ctx.bundle.lexicon.spell(t.folded)
        in {f.ctx.bundle.lexicon.spell(v) for v in f.ctx.bundle.policy.list_of("build_verbs")}
    )
    if not verbs:
        return False, f"no build verb in {f.text!r}"
    if not f.confirmed_matches:
        return False, f"no confirmed technology in {f.text!r}"
    return True, ""


def _confirmed_with_contexts(f: Facts) -> tuple[bool, str]:
    return bool(f.contextful_matches), (
        f"no confirmed technology carrying contexts in {f.text!r}, so the scope "
        f"check has nothing to compare against a role"
    )


def _service_of_a_confirmed_platform(f: Facts) -> tuple[bool, str]:
    """The rule's INPUT, not its verdict.

    Asking whether `service_listed is False` would be asking the gate whether it
    found a violation, which is the circularity this module exists to avoid. The
    input is a sub-service whose platform is confirmed; whether that service is
    on the platform's list is the answer, not the question.
    """
    found = [
        m for m in f.analysis.matches
        if m.resolution.via == "parent_service" and m.resolution.entry is not None
    ]
    return bool(found), (
        f"no sub-service of a confirmed platform in {f.text!r}, so the services "
        f"check is never reached"
    )


def _exposure_technology(f: Facts) -> tuple[bool, str]:
    found = [m for m in f.confirmed_matches if m.resolution.depth == "exposure"]
    return bool(found), f"no exposure-depth technology in {f.text!r}"


def _two_cohabiting(f: Facts) -> tuple[bool, str]:
    counts = f.confirmed_per_sentence()
    best = max(counts.values(), default=0)
    return best >= 2, (
        f"no sentence in {f.text!r} holds two confirmed technologies carrying "
        f"contexts (most in one sentence: {best}). One technology cannot cohabit "
        f"with anything, so this input cannot exercise the rule."
    )


def _numeric_span(f: Facts) -> tuple[bool, str]:
    return bool(f.analysis.numeric_spans), (
        f"the number gate parsed no numeric span from {f.text!r}"
    )


def _vague_input(f: Facts) -> tuple[bool, str]:
    if f.has_any_phrase("vague_intensity_words"):
        return True, ""
    hedged = f.has_any_phrase("leading_hedges") or f.has_any_phrase("trailing_hedges")
    if hedged and f.analysis.numeric_spans:
        return True, ""
    if re.search(r"[~+]", f.text) and f.analysis.numeric_spans:
        return True, ""
    return False, (
        f"{f.text!r} carries neither a vague intensity word nor a hedge beside a "
        f"parsed number"
    )


def _version_shaped(f: Facts) -> tuple[bool, str]:
    for start, _end in f.analysis.numeric_spans:
        for match in f.analysis.matches:
            if match.end <= start and f.text[match.end : start] in ("", " "):
                return True, ""
    return False, f"no number sits directly after a technology name in {f.text!r}"


def _is_bullet(f: Facts) -> tuple[bool, str]:
    return f.block.block_type == BULLET, (
        f"citations are checked on bullets only; this is a {f.block.block_type}"
    )


def _cites_something(f: Facts) -> tuple[bool, str]:
    cited = f.block.fact_ids + f.block.metric_ids
    return bool(cited), "the block cites no ids, so none can be unknown"


def _client_name_in_text(f: Facts) -> tuple[bool, str]:
    """Scanned from the raw text, not from the claim chain.

    Reading the chain's own spans would assert that the gate found something by
    asking the gate whether it found something.
    """
    blocklist = f.ctx.bundle.policy.list_of("client_blocklist")
    if not blocklist:
        return False, "client_blocklist is empty, so CLIENT_NAME can match nothing"
    lowered = " ".join(f.text.lower().split())
    hit = [n for n in blocklist if n.lower() in lowered]
    return bool(hit), f"no blocklist entry appears in {f.text!r}"


def _banned_phrase_in_text(f: Facts) -> tuple[bool, str]:
    lowered = " ".join(f.text.lower().split())
    stems = [p.lower().split()[0][:6] for p in f.ctx.bundle.policy.list_of("banned_phrases")]
    return any(stem in lowered for stem in stems if stem), (
        f"no banned phrase stem appears in {f.text!r}"
    )


def _has_tokens(f: Facts) -> tuple[bool, str]:
    return bool(f.analysis.tokens), f"{f.text!r} has no tokens to open with"


def _dash_in_text(f: Facts) -> tuple[bool, str]:
    present = any(d in f.text for d in (EM_DASH, HORIZONTAL_BAR, DOUBLE_HYPHEN))
    return present, f"no em dash, horizontal bar or double hyphen in {f.text!r}"


def _invisible_in_text(f: Facts) -> tuple[bool, str]:
    return any(c in INVISIBLE_CHARS for c in f.text), (
        f"no invisible character in {f.text!r}"
    )


def _mixed_script_token(f: Facts) -> tuple[bool, str]:
    return any(len(scripts_in(t.raw)) > 1 for t in f.analysis.tokens), (
        f"no token in {f.text!r} mixes scripts"
    )


def _non_latin_token(f: Facts) -> tuple[bool, str]:
    return any(
        any(s != "LATIN" for s in scripts_in(t.raw)) for t in f.analysis.tokens
    ), f"no non-Latin letter in {f.text!r}"


def _jd_copy_possible(f: Facts) -> tuple[bool, str]:
    size = f.ctx.watch.ngram_size
    if not f.ctx.watch.copy_ngrams:
        return False, "the watch list carries no copy ngrams, so JD_COPY can match nothing"
    if len(f.analysis.tokens) < size:
        return False, (
            f"{f.text!r} has {len(f.analysis.tokens)} tokens, fewer than the "
            f"{size}-word window"
        )
    return True, ""


def _watch_list_loaded(f: Facts) -> tuple[bool, str]:
    return bool(f.ctx.watch.terms), (
        "the watch list is empty, so JD_TERM_NOT_IN_EVIDENCE can match nothing"
    )


def _residue_exists(f: Facts) -> tuple[bool, str]:
    residue = [t for t in f.analysis.tokens if not f.analysis.claimed_earlier(t)]
    return bool(residue), (
        f"every token in {f.text!r} was claimed earlier in the chain, so the "
        f"residue heuristic sees nothing"
    )


def _length_limited(f: Facts) -> tuple[bool, str]:
    from app import layout

    return layout.max_lines(f.block.block_type) is not None, (
        f"{f.block.block_type} has no line limit, so TOO_LONG cannot fire"
    )


def _skills_block(f: Facts) -> tuple[bool, str]:
    return f.block.block_type == SKILLS_LINE, (
        f"skills rules apply to skills lines; this is a {f.block.block_type}"
    )


def _proficiency_input(f: Facts) -> tuple[bool, str]:
    ok, message = _skills_block(f)
    if not ok:
        return ok, message
    if f.has_any_phrase("proficiency_qualifiers") or _YEARS_RE.search(f.text):
        return True, ""
    return False, f"no proficiency qualifier or years construction in {f.text!r}"


def _unverifiable_input(f: Facts) -> tuple[bool, str]:
    return f.has_any_phrase("unverifiable_labels"), (
        f"no unverifiable label from policy appears in {f.text!r}"
    )


def _title_shaped(f: Facts) -> tuple[bool, str]:
    if f.block.block_type != SUMMARY:
        return False, f"title claims are checked in the summary; this is a {f.block.block_type}"
    run = 0
    for token in f.analysis.tokens:
        run = run + 1 if token.raw[:1].isupper() else 0
        if run >= 2:
            return True, ""
    return False, f"no run of two capitalised words in {f.text!r}"


def _uncited_block(f: Facts) -> tuple[bool, str]:
    if f.block.block_type == BULLET:
        return False, "UNCITED_NUMBER fires where no citation exists; this is a bullet"
    return True, ""


PRECONDITIONS = {
    "TECH_DENIED": _taxonomy_match,
    "TECH_UNCONFIRMED": _taxonomy_match,
    "JD_TERM_NOT_IN_EVIDENCE": _watch_list_loaded,
    "UNKNOWN_TERM": _residue_exists,
    "SCOPE_DEPTH": _build_verb_and_technology,
    "SCOPE_CONTEXT": _confirmed_with_contexts,
    "SCOPE_SERVICE": _service_of_a_confirmed_platform,
    "SCOPE_EXPOSURE_IN_BULLET": _exposure_technology,
    "SKILLS_EXPOSURE": _exposure_technology,
    "SCOPE_COHABITATION": _two_cohabiting,
    "NUMBER_UNSUPPORTED": _numeric_span,
    "NUMBER_FORM_MISMATCH": _numeric_span,
    "UNCITED_NUMBER": _uncited_block,
    "VAGUE_METRIC": _vague_input,
    "VERSION_UNSUPPORTED": _version_shaped,
    "CITATION_MISSING": _is_bullet,
    "CITATION_UNKNOWN": _cites_something,
    "CLIENT_NAME": _client_name_in_text,
    "BANNED_VERB": _banned_phrase_in_text,
    "WEAK_OPENING": _has_tokens,
    "OPENING_VERB_UNLISTED": _has_tokens,
    "EM_DASH": _dash_in_text,
    "INVISIBLE_CHAR": _invisible_in_text,
    "MIXED_SCRIPT": _mixed_script_token,
    "NON_LATIN_SCRIPT": _non_latin_token,
    "JD_COPY": _jd_copy_possible,
    "TOO_LONG": _length_limited,
    "SKILLS_PROFICIENCY": _proficiency_input,
    "UNVERIFIABLE_LABEL": _unverifiable_input,
    "TITLE_CLAIM_UNVERIFIED": _title_shaped,
}

#: Codes whose precondition is a property of the document, not of one block.
DOCUMENT_CODES = frozenset({"BULLET_COUNT"})


def check_precondition(code: str, block: Block, ctx) -> None:
    """Raise unless the input still contains what `code`'s rule needs."""
    if code in DOCUMENT_CODES:
        return
    predicate = PRECONDITIONS.get(code)
    if predicate is None:
        raise PreconditionError(
            f"{code} has no precondition. Every rejection code needs one, or a "
            f"test asserting it can go green while asserting nothing."
        )
    ok, message = predicate(facts_for(block, ctx))
    if not ok:
        raise PreconditionError(f"precondition for {code} does not hold: {message}")


def check_document_precondition(code: str, document: Document, ctx) -> None:
    if code == "BULLET_COUNT":
        by_role = document.bullets_by_role()
        limit = int(ctx.bundle.policy["max_bullets_per_role"])
        worst = max((len(b) for b in by_role.values()), default=0)
        if worst <= limit:
            raise PreconditionError(
                f"precondition for BULLET_COUNT does not hold: no role carries more "
                f"than the limit of {limit} (most in one role: {worst})"
            )
        return
    for block in document.blocks:
        try:
            check_precondition(code, block, ctx)
            return
        except PreconditionError:
            continue
    raise PreconditionError(
        f"precondition for {code} holds in no block of this document"
    )
