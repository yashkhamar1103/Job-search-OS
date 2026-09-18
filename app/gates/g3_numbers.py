"""G3, the number gate. Pure function. No model call, no network.

Citations, numbers, versions, and vague intensity words.

In a bullet, every numeric expression must equal a value in that bullet's cited
metrics. In the summary and the skills section there is nothing to cite, so
every number is rejected with one exception: a value this codebase computed
itself, rendered in a form the computed registry allows. A model cannot put a
number there, and cannot widen the registry.

A number that is part of a product name is not a claim about scale. OAuth 2.0,
Route 53, and SOC 2 all carry digits that belong to the name, so a number inside
a matched alias is skipped. A number directly after one is a version, checked
against that entry's versions list rather than against a metric.
"""

from __future__ import annotations

from app.errors import GateResult, Rejection
from app.gates.context import BlockAnalysis, GateContext, MatchedTech
from app.models import BULLET, CLAIM_BLOCKS
from app.normalise import token_texts
from app.numbers import extract, supported_keys, word_value

#: What may sit between a technology name and its version: nothing, or a single
#: space. Anything else, a comma above all, means the number belongs to the next
#: item in a list rather than to the technology. Allowing punctuation here made
#: "Python, 5 years" read 5 as a version of Python.
_VERSION_GAPS = ("", " ")


def check(analysis: BlockAnalysis, ctx: GateContext) -> GateResult:
    if analysis.block.block_type not in CLAIM_BLOCKS:
        return GateResult()

    rejections: list[Rejection] = []
    if analysis.block.block_type == BULLET:
        citation_errors = list(_citations(analysis, ctx))
        rejections.extend(citation_errors)
    rejections.extend(_vague_words(analysis, ctx))
    rejections.extend(_numbers(analysis, ctx))
    return GateResult(tuple(rejections))


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


def _citations(analysis: BlockAnalysis, ctx: GateContext):
    block = analysis.block
    facts = ctx.bundle.experience.facts_by_id
    metrics = ctx.bundle.experience.metrics_by_id

    if not block.fact_ids:
        yield analysis.reject(
            "CITATION_MISSING",
            analysis.whole_span(),
            "a bullet must cite at least one fact_id",
        )

    for fact_id in block.fact_ids:
        if fact_id not in facts:
            yield analysis.reject(
                "CITATION_UNKNOWN",
                analysis.whole_span(),
                f"fact_id {fact_id!r} is not in experience.json",
                cited_id=fact_id,
            )
    for metric_id in block.metric_ids:
        if metric_id not in metrics:
            yield analysis.reject(
                "CITATION_UNKNOWN",
                analysis.whole_span(),
                f"metric_id {metric_id!r} is not in experience.json",
                cited_id=metric_id,
            )


def cited_metric_values(analysis: BlockAnalysis, ctx: GateContext) -> list[str]:
    metrics = ctx.bundle.experience.metrics_by_id
    return [metrics[m].value for m in analysis.block.metric_ids if m in metrics]


# ---------------------------------------------------------------------------
# Vague intensity words
# ---------------------------------------------------------------------------


def _vague_words(analysis: BlockAnalysis, ctx: GateContext):
    lexicon = ctx.bundle.lexicon
    vague = {
        lexicon.spell(w.lower()) for w in ctx.bundle.policy.list_of("vague_intensity_words")
    }
    is_bullet = analysis.block.block_type == BULLET
    code = "VAGUE_METRIC" if is_bullet else "UNCITED_NUMBER"
    for token in analysis.tokens:
        if lexicon.spell(token.folded) not in vague:
            continue
        yield analysis.reject(
            code,
            analysis.token_span(token),
            f"{token.raw!r} implies a number that does not exist",
            word=token.raw,
        )


# ---------------------------------------------------------------------------
# Numbers and versions
# ---------------------------------------------------------------------------


def _inside_alias(analysis: BlockAnalysis, start: int, end: int) -> bool:
    return any(m.start <= start and end <= m.end for m in analysis.matches)


def _version_owner(analysis: BlockAnalysis, start: int) -> MatchedTech | None:
    for matched in analysis.matches:
        if matched.end <= start and analysis.block.text[matched.end : start] in _VERSION_GAPS:
            return matched
    return None


def _numbers(analysis: BlockAnalysis, ctx: GateContext):
    block = analysis.block
    is_bullet = block.block_type == BULLET
    supported = supported_keys(cited_metric_values(analysis, ctx)) if is_bullet else frozenset()
    allowed_years = set(ctx.computed.allowed_year_renderings)

    year_token_spans = _computed_year_spans(analysis, allowed_years) if not is_bullet else set()

    # The computed years rendering is code-generated from the role dates, so
    # its trailing plus is not a model widening a number it was given.
    computed_years = _computed_year_spans(analysis, allowed_years)
    yield from _hedged_numbers(analysis, ctx, computed_years)

    # In a block with no citations, a hedged duration is its own defect even
    # with no digits nearby: "nearly a decade" is a number with no value.
    if not is_bullet:
        yield from _duration_hedges(analysis, ctx)

    for expression in extract(analysis.norm.text):
        origin_start, origin_end = analysis.norm.origin(expression.start, expression.end)
        if _inside_alias(analysis, origin_start, origin_end):
            continue

        owner = _version_owner(analysis, origin_start)
        if owner is not None:
            yield from _version(analysis, ctx, owner, origin_start, origin_end, expression.raw)
            continue

        span = analysis.span(origin_start, origin_end)

        if not is_bullet:
            if (origin_start, origin_end) in year_token_spans:
                continue
            yield analysis.reject(
                "UNCITED_NUMBER",
                span,
                f"{expression.raw.strip()!r} has no citation available in a "
                f"{block.block_type} and is not a computed value",
            )
            continue

        if expression.key not in supported:
            yield _number_finding(
                analysis, ctx, span, expression.raw.strip(), expression.canonical, supported
            )

    yield from _number_words(analysis, ctx, supported, is_bullet)


#: How many whole tokens may sit between a leading hedge and the number it
#: qualifies. One, so "roughly 40%" and "about the 40%" both count.
_LEADING_HEDGE_GAP = 1

#: Characters that hedge without being tokens. "~" leads, "+" trails.
_TILDE = "~"
_PLUS = "+"


def _phrase_positions(analysis: BlockAnalysis, phrases: tuple[str, ...]):
    """Every occurrence of any phrase, longest first, as (first, last, phrase)."""
    text_tokens = tuple(t.folded for t in analysis.tokens)
    wanted = sorted(
        ((token_texts(p), p) for p in phrases),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    consumed: set[int] = set()
    for seq, phrase in wanted:
        if not seq:
            continue
        for i in range(0, max(0, len(text_tokens) - len(seq) + 1)):
            if text_tokens[i : i + len(seq)] != seq:
                continue
            window = analysis.tokens[i : i + len(seq)]
            if any(t.index in consumed for t in window):
                continue
            consumed.update(t.index for t in window)
            yield window[0], window[-1], phrase


def _tokens_between(analysis: BlockAnalysis, left_end: int, right_start: int) -> int:
    """How many whole tokens sit strictly between two character offsets."""
    if right_start < left_end:
        return -1
    return sum(1 for t in analysis.tokens if left_end <= t.start and t.end <= right_start)


def _hedged_numbers(analysis: BlockAnalysis, ctx: GateContext, exempt: set[tuple[int, int]]):
    """A hedge attached to a number, by position.

    Position is the whole rule. The same word hedges in one place and does not
    in another: "over 6 years" widens a number, "3x over the prior pipeline"
    compares one thing to another, and "over the weekend window" is a
    preposition with no number in sight. Checking presence rather than position
    blocked all three.
    """
    if not analysis.numeric_spans:
        return

    text = analysis.block.text
    leading = tuple(ctx.bundle.policy.list_of("leading_hedges"))
    trailing = tuple(ctx.bundle.policy.list_of("trailing_hedges"))

    word_leading = tuple(h for h in leading if h != _TILDE)
    word_trailing = tuple(h for h in trailing if h != _PLUS)

    for start, end in analysis.numeric_spans:
        # A tilde immediately before the number, which is not a token.
        before = text[:start].rstrip()
        if before.endswith(_TILDE):
            yield analysis.reject(
                "VAGUE_METRIC",
                analysis.span(len(before) - 1, end),
                f"{_TILDE!r} hedges {text[start:end]!r}",
                hedge=_TILDE,
            )
            continue

        # A trailing plus carried inside the numeric token itself.
        #
        # The exemption is scoped to trailing hedges alone, which is where the
        # directive puts it. "6+ years" is code-generated from the role dates.
        # "over 6 years" is not: the hedge sits in front, and a leading hedge on
        # a computed value is still the model widening a number it was handed.
        if (start, end) in exempt:
            pass
        elif text[start:end].rstrip().endswith(_PLUS):
            yield analysis.reject(
                "VAGUE_METRIC",
                analysis.span(start, end),
                f"{text[start:end]!r} widens a number that a metric records exactly",
                hedge=_PLUS,
            )
            continue

        hedged = False
        for first, last, phrase in _phrase_positions(analysis, word_leading):
            if 0 <= _tokens_between(analysis, last.end, start) <= _LEADING_HEDGE_GAP:
                yield analysis.reject(
                    "VAGUE_METRIC",
                    analysis.span(first.start, end),
                    f"{phrase!r} precedes {text[start:end]!r}. A measured value is "
                    f"not approximate, and an approximate one is not evidence.",
                    hedge=phrase,
                )
                hedged = True
                break
        if hedged:
            continue

        if (start, end) in exempt:
            continue

        for first, last, phrase in _phrase_positions(analysis, word_trailing):
            if 0 <= _tokens_between(analysis, end, first.start) <= 0:
                yield analysis.reject(
                    "VAGUE_METRIC",
                    analysis.span(start, last.end),
                    f"{phrase!r} follows {text[start:end]!r} and widens it beyond "
                    f"what the metric records",
                    hedge=phrase,
                )
                break


def _duration_hedges(analysis: BlockAnalysis, ctx: GateContext):
    """Hedged durations, matched as phrases.

    "more than" and "half a decade" are several tokens each. Checking single
    tokens only would let the multi-word hedges straight through, which is the
    half of the list that matters most.
    """
    text_tokens = tuple(t.folded for t in analysis.tokens)
    phrases = [token_texts(h) for h in ctx.bundle.policy.list_of("duration_hedges")]
    phrases = sorted((p for p in phrases if p), key=len, reverse=True)
    consumed: set[int] = set()
    for wanted in phrases:
        for i in range(0, max(0, len(text_tokens) - len(wanted) + 1)):
            if text_tokens[i : i + len(wanted)] != wanted:
                continue
            window = analysis.tokens[i : i + len(wanted)]
            if any(t.index in consumed for t in window):
                continue
            consumed.update(t.index for t in window)
            yield analysis.reject(
                "UNCITED_NUMBER",
                analysis.span(window[0].start, window[-1].end),
                f"{' '.join(wanted)!r} hedges a duration, which is a number without a value",
                phrase=" ".join(wanted),
            )


def _number_words(analysis, ctx, supported, is_bullet):
    for token in analysis.tokens:
        if token.index in analysis.covered:
            continue
        canonical = word_value(token.folded)
        if canonical is None:
            continue
        span = analysis.token_span(token)
        if not is_bullet:
            yield analysis.reject(
                "UNCITED_NUMBER",
                span,
                f"{token.raw!r} is a number word with no citation available here",
            )
        elif canonical.key() not in supported:
            yield _number_finding(analysis, ctx, span, token.raw, canonical, supported)


def _computed_year_spans(analysis: BlockAnalysis, allowed: set[tuple[str, ...]]) -> set[tuple[int, int]]:
    """Spans of a permitted years-of-experience rendering.

    Only an exact match of a form the computed registry allows, which means the
    figure equals the total this codebase derived from the role dates. Anything
    else, including a hedge such as nearly five years, is not a computed value.
    """
    spans: set[tuple[int, int]] = set()
    tokens = analysis.tokens
    widths = {len(form) for form in allowed}
    for i, token in enumerate(tokens):
        for width in widths:
            if i + width > len(tokens):
                continue
            window = tokens[i : i + width]
            if tuple(t.folded for t in window) in allowed:
                spans.add((window[0].start, window[0].end))
    return spans


def _version(analysis: BlockAnalysis, ctx: GateContext, owner: MatchedTech, start: int, end: int, raw: str):
    resolution = owner.resolution
    entry = resolution.entry
    versions = entry.versions if entry else ()
    candidate = raw.strip()
    if resolution.confirmed and candidate in versions:
        return
    yield analysis.reject(
        "VERSION_UNSUPPORTED",
        analysis.span(start, end),
        f"{candidate!r} is attached to {resolution.canonical_id} but its versions list is "
        f"{list(versions) or 'empty'}",
        canonical_id=resolution.canonical_id,
        version=candidate,
    )


def _number_finding(analysis, ctx, span, surface, canonical, supported):
    """NUMBER_UNSUPPORTED or NUMBER_FORM_MISMATCH, whichever is true.

    They are different defects and a retry should be told which. A value that
    is simply absent from the cited metrics means the model invented it. A
    value that matches but in the wrong form means the model has the right
    metric and rendered it as something else, so naming the metric's own form
    lets the retry converge instead of guessing at a number it already has.
    """
    from app.numbers import _canonical_text

    values = cited_metric_values(analysis, ctx)
    mine = _canonical_text(canonical.value)
    same_value = sorted(
        {key for key in supported if key[2] == mine}
    )
    if same_value:
        forms = ", ".join(f"{k[0]}{(' ' + k[1]) if k[1] else ''}" for k in same_value)
        return analysis.reject(
            "NUMBER_FORM_MISMATCH",
            span,
            f"{surface!r} matches a cited metric's value but not its form. The "
            f"metric records it as {forms}; rewrite to that form.",
            recorded_as=forms,
        )
    return analysis.reject(
        "NUMBER_UNSUPPORTED",
        span,
        f"{surface!r} does not equal a value in the bullet's cited metrics "
        f"({', '.join(values) or 'none cited'})",
    )
