"""G4, the structure and style gate. Pure function. No model call, no network.

Bullet count, banned phrases, opening verbs, dashes, client names, copied job
description text, rendered length, and the skills section's own rules.

WEAK_OPENING is a denylist, not an allowlist check. A bullet is rejected for
opening badly: with a weak opener phrase, an -ing or -ly word, a form of be or
have, or with no verb in its first two tokens.

policy.opening_verbs is coverage, not enforcement. An opening verb that clears
the denylist but is not in the list reports OPENING_VERB_UNLISTED, which never
rejects, and the finding carries the exact config line to add. Enforcing the
list would mean a perfectly good verb nobody thought of gets a truthful bullet
dropped, which is a style rule deciding a question of fact.
"""

from __future__ import annotations

import re

from app import layout
from app.errors import GateResult, Rejection
from app.gates.context import BlockAnalysis, GateContext
from app.models import BULLET, CLAIM_BLOCKS, HEADER, SKILLS_LINE, SUMMARY, Document
from app.normalise import Token, ngrams, token_texts, tokens_of

#: The banned dashes, built from code points so that this file obeys the rule
#: it enforces. A literal em dash in the pattern would be a violation sitting
#: inside the check for violations.
EM_DASH = chr(0x2014)
HORIZONTAL_BAR = chr(0x2015)
DOUBLE_HYPHEN = "--"
_DASH_RE = re.compile(f"[{EM_DASH}{HORIZONTAL_BAR}]|{DOUBLE_HYPHEN}")

_ED_RE = re.compile(r"^[a-z][a-z]*ed$")
_ING_RE = re.compile(r"(?i)ing$")
_LY_RE = re.compile(r"(?i)ly$")
_YEARS_RE = re.compile(r"(?i)\b\d+\s*\+?\s*(?:year|yr)s?\b")

_NO_STRIP_S_ENDINGS = ("ss", "us", "is")


def check(analysis: BlockAnalysis, ctx: GateContext) -> GateResult:
    rejections: list[Rejection] = []
    rejections.extend(_dashes(analysis))
    rejections.extend(_client_names(analysis, ctx))

    if analysis.block.block_type in CLAIM_BLOCKS:
        rejections.extend(_banned_phrases(analysis, ctx))
        rejections.extend(_too_long(analysis))

    if analysis.block.block_type in (BULLET, SUMMARY):
        rejections.extend(_unverifiable_labels(analysis, ctx))

    if analysis.block.block_type == SUMMARY:
        rejections.extend(_title_claims(analysis, ctx))

    if analysis.block.block_type == BULLET:
        rejections.extend(_opening(analysis, ctx))
        rejections.extend(_jd_copy(analysis, ctx))

    if analysis.block.block_type == SKILLS_LINE:
        rejections.extend(_skills_rules(analysis, ctx))

    return GateResult(tuple(rejections))


# ---------------------------------------------------------------------------
# Stemming, for lemma-aware phrase matching
# ---------------------------------------------------------------------------


def _stem(word: str) -> str:
    """A crude stem, enough to make a banned phrase lemma-aware.

    Not a linguistic stemmer. It exists so that a six-entry banned list catches
    spearheading and spearheads without six more entries, and it is applied to
    both the config entry and the text so an over-eager strip cannot cause a
    miss.
    """
    stem = word
    for suffix in ("ing", "ed", "es", "s"):
        if not stem.endswith(suffix):
            continue
        if suffix in ("es", "s") and stem.endswith(_NO_STRIP_S_ENDINGS):
            continue
        if len(stem) - len(suffix) < 3:
            continue
        stem = stem[: -len(suffix)]
        break
    if len(stem) > 3 and stem.endswith("e"):
        stem = stem[:-1]
    return stem


def _stems(tokens: tuple[Token, ...], ctx: GateContext) -> tuple[str, ...]:
    return tuple(_stem(ctx.bundle.lexicon.spell(t.folded)) for t in tokens)


def _phrase_stems(phrase: str, ctx: GateContext) -> tuple[str, ...]:
    return tuple(_stem(ctx.bundle.lexicon.spell(t)) for t in token_texts(phrase))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _dashes(analysis: BlockAnalysis):
    for match in _DASH_RE.finditer(analysis.block.text):
        yield analysis.reject(
            "EM_DASH",
            analysis.span(match.start(), match.end()),
            "em dash, horizontal bar, and double hyphen are all banned",
        )


def _banned_phrases(analysis: BlockAnalysis, ctx: GateContext):
    text_stems = _stems(analysis.tokens, ctx)
    for phrase in ctx.bundle.policy.list_of("banned_phrases"):
        wanted = _phrase_stems(phrase, ctx)
        if not wanted:
            continue
        for i in range(0, max(0, len(text_stems) - len(wanted) + 1)):
            if text_stems[i : i + len(wanted)] != wanted:
                continue
            window = analysis.tokens[i : i + len(wanted)]
            yield analysis.reject(
                "BANNED_VERB",
                analysis.span(window[0].start, window[-1].end),
                f"banned phrase {phrase!r}",
                phrase=phrase,
            )


def _client_names(analysis: BlockAnalysis, ctx: GateContext):
    """Blocklisted client names, read from the claim chain.

    The chain matched longest first and non-overlapping, so a blocklist holding
    both "Northwind Retail" and "Northwind" reports the name once, not twice.
    """
    for span in analysis.client_spans:
        name = analysis.client_name_at(span, ctx)
        yield analysis.reject(
            "CLIENT_NAME",
            analysis.span(*span),
            f"blocklisted client name {name!r}",
            name=name,
        )


def _jd_copy(analysis: BlockAnalysis, ctx: GateContext):
    size = ctx.watch.ngram_size
    if not ctx.watch.copy_ngrams or size <= 0:
        return
    for gram, first, last in ngrams(analysis.tokens, size):
        if gram not in ctx.watch.copy_ngrams:
            continue
        yield analysis.reject(
            "JD_COPY",
            analysis.span(first.start, last.end),
            f"{size} consecutive words are shared with the job description",
        )


def _too_long(analysis: BlockAnalysis):
    limit = layout.max_lines(analysis.block.block_type)
    if limit is None:
        return
    lines = layout.measure_lines(analysis.block.block_type, analysis.block.measurable_markup)
    if lines > limit:
        yield analysis.reject(
            "TOO_LONG",
            analysis.whole_span(),
            f"wraps to {lines} rendered lines, limit {limit} "
            f"(layout version {layout.LAYOUT_VERSION})",
            lines=str(lines),
            limit=str(limit),
        )


# ---------------------------------------------------------------------------
# Opening verb
# ---------------------------------------------------------------------------


def _is_verb_like(token: Token, ctx: GateContext) -> bool:
    lexicon = ctx.bundle.lexicon
    spelled = lexicon.spell(token.folded)
    if spelled in _single_opening_verbs(ctx):
        return True
    if spelled in lexicon.irregular_past:
        return True
    return bool(_ED_RE.match(spelled)) and spelled not in lexicon.non_verb_ed


def _single_opening_verbs(ctx: GateContext) -> frozenset[str]:
    lexicon = ctx.bundle.lexicon
    return frozenset(
        lexicon.spell(v.lower())
        for v in ctx.bundle.policy.list_of("opening_verbs")
        if len(token_texts(v)) == 1
    )


def _phrase_lists(entries: tuple[str, ...], ctx: GateContext) -> list[tuple[str, ...]]:
    """Config entries as spelled token tuples, longest first."""
    out = [
        tuple(ctx.bundle.lexicon.spell(t) for t in token_texts(entry))
        for entry in entries
    ]
    out = [seq for seq in out if seq]
    out.sort(key=len, reverse=True)
    return out


def _opening(analysis: BlockAnalysis, ctx: GateContext):
    tokens = analysis.tokens
    if not tokens:
        yield analysis.reject("WEAK_OPENING", analysis.whole_span(), "the bullet is empty")
        return

    lexicon = ctx.bundle.lexicon
    spelled = [lexicon.spell(t.folded) for t in tokens]

    weak = _phrase_lists(ctx.bundle.policy.list_of("weak_openers"), ctx)
    for wanted in weak:
        if tuple(spelled[: len(wanted)]) == wanted:
            window = tokens[: len(wanted)]
            yield analysis.reject(
                "WEAK_OPENING",
                analysis.span(window[0].start, window[-1].end),
                f"opens with the weak opener {' '.join(wanted)!r}",
                reason="weak_opener",
            )
            return

    first = tokens[0]
    if _ING_RE.search(first.folded) or _LY_RE.search(first.folded):
        yield analysis.reject(
            "WEAK_OPENING",
            analysis.token_span(first),
            f"opens with {first.raw!r}, which is an -ing or -ly word",
            reason="ing_or_ly",
        )
        return

    if first.folded in {v.lower() for v in ctx.bundle.policy.list_of("be_have_openers")}:
        yield analysis.reject(
            "WEAK_OPENING",
            analysis.token_span(first),
            f"opens with {first.raw!r}, a form of be or have",
            reason="be_or_have",
        )
        return

    listed = _phrase_lists(ctx.bundle.policy.list_of("opening_verbs"), ctx)
    for wanted in listed:
        if len(wanted) > 1 and tuple(spelled[: len(wanted)]) == wanted:
            return

    head = tokens[:2]
    verb = next((t for t in head if _is_verb_like(t, ctx)), None)
    if verb is None:
        yield analysis.reject(
            "WEAK_OPENING",
            analysis.span(head[0].start, head[-1].end),
            "no verb in the first two tokens",
            reason="no_verb",
        )
        return

    if lexicon.spell(verb.folded) not in _single_opening_verbs(ctx):
        yield analysis.reject(
            "OPENING_VERB_UNLISTED",
            analysis.token_span(verb),
            f"{verb.raw!r} passed the denylist but is not in policy.opening_verbs. "
            f'Add it with:  "{verb.folded}",',
            verb=verb.folded,
            config_line=f'  "{verb.folded}",',
        )


# ---------------------------------------------------------------------------
# Skills section
# ---------------------------------------------------------------------------


def _skills_rules(analysis: BlockAnalysis, ctx: GateContext):
    for matched in analysis.matches:
        resolution = matched.resolution
        if resolution.confirmed and resolution.depth == "exposure":
            yield analysis.reject(
                "SKILLS_EXPOSURE",
                analysis.match_span(matched),
                f"{resolution.canonical_id} has depth exposure and may not appear in "
                f"the skills section",
                canonical_id=resolution.canonical_id,
            )

    text_tokens = tuple(t.folded for t in analysis.tokens)
    for qualifier in ctx.bundle.policy.list_of("proficiency_qualifiers"):
        wanted = token_texts(qualifier)
        if not wanted:
            continue
        for i in range(0, max(0, len(text_tokens) - len(wanted) + 1)):
            if text_tokens[i : i + len(wanted)] != wanted:
                continue
            window = analysis.tokens[i : i + len(wanted)]
            yield analysis.reject(
                "SKILLS_PROFICIENCY",
                analysis.span(window[0].start, window[-1].end),
                f"proficiency qualifier {qualifier!r} is an unevidenced self-assessment",
                qualifier=qualifier,
            )

    for match in _YEARS_RE.finditer(analysis.block.text):
        yield analysis.reject(
            "SKILLS_PROFICIENCY",
            analysis.span(match.start(), match.end()),
            "a years construction in the skills section is a proficiency claim",
        )


# ---------------------------------------------------------------------------
# Document-level checks
# ---------------------------------------------------------------------------


def check_document(document: Document, ctx: GateContext) -> GateResult:
    """Checks that no single block can answer: bullet counts, and client names
    in filenames and document metadata."""
    from app.errors import Span

    rejections: list[Rejection] = []
    limit = int(ctx.bundle.policy["max_bullets_per_role"])
    for role_id, bullets in document.bullets_by_role().items():
        if len(bullets) <= limit:
            continue
        rejections.append(
            Rejection(
                code="BULLET_COUNT",
                span=Span(0, len(role_id) or 1, role_id),
                detail=f"role {role_id!r} has {len(bullets)} bullets, limit {limit}",
                block_id=role_id,
                context={"role_id": role_id, "count": str(len(bullets))},
            )
        )

    blocklist = ctx.bundle.policy.list_of("client_blocklist")
    if blocklist:
        targets = {"filename": document.filename_stem}
        targets.update({f"metadata.{k}": v for k, v in document.metadata.items()})
        for where, value in targets.items():
            if not value:
                continue
            found = tuple(t.folded for t in tokens_of(value))
            for name in blocklist:
                wanted = token_texts(name)
                if not wanted:
                    continue
                for i in range(0, max(0, len(found) - len(wanted) + 1)):
                    if found[i : i + len(wanted)] != wanted:
                        continue
                    rejections.append(
                        Rejection(
                            code="CLIENT_NAME",
                            span=Span(0, len(value), value),
                            detail=f"blocklisted client name {name!r} in {where}",
                            block_id=where,
                            context={"name": name, "where": where},
                        )
                    )
    return GateResult(tuple(rejections))


# ---------------------------------------------------------------------------
# Unverifiable claims
# ---------------------------------------------------------------------------


def _phrase_hits(analysis: BlockAnalysis, phrases: tuple[str, ...]):
    """Every occurrence of any phrase, as (first token, last token, phrase)."""
    text_tokens = tuple(t.folded for t in analysis.tokens)
    for phrase in phrases:
        wanted = token_texts(phrase)
        if not wanted:
            continue
        for i in range(0, max(0, len(text_tokens) - len(wanted) + 1)):
            if text_tokens[i : i + len(wanted)] != wanted:
                continue
            window = analysis.tokens[i : i + len(wanted)]
            yield window[0], window[-1], phrase


def _unverifiable_labels(analysis: BlockAnalysis, ctx: GateContext):
    """Self-description no evidence can support or refute.

    Style bucket rather than truth: "seasoned" is not a false claim about a
    technology, it is a claim with no truth value at all. It gets one retry and
    then renders flagged, because dropping a bullet over an adjective would be
    a style rule deciding a question of fact.
    """
    for first, last, phrase in _phrase_hits(
        analysis, ctx.bundle.policy.list_of("unverifiable_labels")
    ):
        yield analysis.reject(
            "UNVERIFIABLE_LABEL",
            analysis.span(first.start, last.end),
            f"{phrase!r} asserts a quality no evidence can support or refute",
            label=phrase,
        )


# ---------------------------------------------------------------------------
# Title claims
# ---------------------------------------------------------------------------


def _held_titles(ctx: GateContext) -> frozenset[tuple[str, ...]]:
    return frozenset(token_texts(role.title) for role in ctx.bundle.experience.roles)


def _title_claims(analysis: BlockAnalysis, ctx: GateContext):
    """A job-title-shaped phrase in prose that matches no title actually held.

    Advisory, never a rejection. The header headline is the posting's exact job
    title and is exempt by block type: claiming to be applying for a role is not
    the same as claiming to have held it.

    A run of capitalised words ending in a title noun, two tokens or more. One
    token is not enough: a summary opening with "Engineer building ..." has
    capitalised its first word because it is the first word, and reading that as
    a title claim would flag almost every summary ever written.
    """
    if analysis.block.block_type == HEADER:
        return

    nouns = {n.lower() for n in ctx.bundle.policy.list_of("title_nouns")}
    modifiers = {m.lower() for m in ctx.bundle.policy.list_of("title_modifiers")}
    held = _held_titles(ctx)

    tokens = analysis.tokens
    i = 0
    while i < len(tokens):
        if not tokens[i].raw[:1].isupper():
            i += 1
            continue
        j = i
        while j + 1 < len(tokens) and tokens[j + 1].raw[:1].isupper():
            j += 1
        run = tokens[i : j + 1]
        i = j + 1

        if len(run) < 2:
            continue
        if run[-1].folded not in nouns:
            continue
        if not any(t.folded in nouns or t.folded in modifiers for t in run[:-1]):
            continue

        claimed = tuple(t.folded for t in run)
        if claimed in held:
            continue
        yield analysis.reject(
            "TITLE_CLAIM_UNVERIFIED",
            analysis.span(run[0].start, run[-1].end),
            f"{analysis.block.text[run[0].start : run[-1].end]!r} matches no title in "
            f"experience.json ({', '.join(sorted(' '.join(t) for t in held)) or 'none'})",
            claimed=" ".join(claimed),
        )
