"""G1, the technology gate. Pure function. No model call, no network.

Four checks, run over bullets, the summary, and the skills section alike,
because an unsupported claim in a skills line is the same claim it would be in a
bullet.

  Taxonomy check      Every term the taxonomy knows must resolve to a confirmed
                      ledger entry.
  Watch-list check    A term drawn from the posting must be in the evidence
                      corpus. This is the primary defence: the posting is where
                      fabrications come from.
  Unknown terms       A proper-noun-shaped token the taxonomy does not know and
                      the evidence does not contain is held for review.
  Ambiguous acronyms  Matched as whole tokens, never inside a word, and never
                      widened by the plural tolerance.

The services case is deliberately reported twice. A sub-service its platform
never listed is not confirmed, so G1 rejects it as unconfirmed, and G2 adds the
precise reason. Each gate stays independently correct rather than relying on the
other having run.
"""

from __future__ import annotations

from app.errors import GateResult, Rejection
from app.gates.context import DENIED, BlockAnalysis, GateContext
from app.models import CLAIM_BLOCKS
from app.normalise import proper_noun_signal, token_texts


def check(analysis: BlockAnalysis, ctx: GateContext) -> GateResult:
    if analysis.block.block_type not in CLAIM_BLOCKS:
        return GateResult()

    rejections: list[Rejection] = []
    rejections.extend(_taxonomy_check(analysis, ctx))
    watch_spans = list(_watch_list_check(analysis, ctx))
    rejections.extend(r for r, _ in watch_spans)
    claimed = {index for _, indices in watch_spans for index in indices}
    rejections.extend(_unknown_terms(analysis, ctx, claimed))
    return GateResult(tuple(rejections))


def _taxonomy_check(analysis: BlockAnalysis, ctx: GateContext):
    for matched in analysis.matches:
        resolution = matched.resolution
        if resolution.confirmed:
            continue
        code = "TECH_DENIED" if resolution.state == DENIED else "TECH_UNCONFIRMED"
        detail = (
            f"{ctx.bundle.taxonomy.display(resolution.canonical_id)} "
            f"resolves to {resolution.canonical_id}, state {resolution.state}"
        )
        yield analysis.reject(
            code,
            analysis.match_span(matched),
            detail,
            canonical_id=resolution.canonical_id,
            via=resolution.via,
        )


def _watch_list_check(analysis: BlockAnalysis, ctx: GateContext):
    """Yield (rejection, token indices) for posting terms absent from evidence.

    A synonyms entry is what makes an employer's wording permissible when the
    literal term is not in the evidence. That is the one widening, and it lives
    in Corpus.permitted rather than in the corpus itself, so it stays visible.
    """
    if not ctx.watch.terms:
        return
    corpus = ctx.bundle.corpus
    for match in ctx.watch_index.match(analysis.tokens):
        key = tuple(t.folded for t in match.tokens)
        if corpus.permitted(key):
            continue
        span = analysis.span(match.start, match.end)
        yield (
            analysis.reject(
                "JD_TERM_NOT_IN_EVIDENCE",
                span,
                f"{' '.join(key)} appears in the job description but not in the evidence corpus",
                term=" ".join(key),
            ),
            tuple(t.index for t in match.tokens),
        )


def _unknown_terms(analysis: BlockAnalysis, ctx: GateContext, claimed: set[int]):
    corpus = ctx.bundle.corpus
    for token in analysis.tokens:
        if token.index in analysis.covered or token.index in claimed:
            continue
        # Gate precedence: a span G3 already claims as a number or a version is
        # never a product name, whether or not it validated.
        if analysis.claimed_by_a_number(token):
            continue
        if corpus.contains((token.folded,)):
            continue
        signal = proper_noun_signal(
            token,
            sentence_initial=token.index in analysis.sentence_openers,
            wordlist=ctx.bundle.lexicon.wordlist,
        )
        if signal is None:
            continue
        yield analysis.reject(
            "UNKNOWN_TERM",
            analysis.token_span(token),
            f"{token.raw!r} is in neither the taxonomy nor the evidence corpus ({signal})",
            signal=signal,
        )


def ambiguous_acronym_ids(ctx: GateContext) -> dict[str, str | None]:
    """Each configured ambiguous acronym and the canonical id it resolves to.

    Exposed so a test can assert every configured acronym is actually in the
    taxonomy. An acronym the taxonomy does not know is matched by nothing, and a
    check that matches nothing is a check that is not running.
    """
    index = ctx.bundle.taxonomy.index
    return {acronym: index.resolve(acronym) for acronym in ctx.bundle.policy.list_of("ambiguous_acronyms")}


def acronym_is_whole_token_only(acronym: str) -> bool:
    """True when an acronym is short enough that plural tolerance cannot widen it.

    The tolerance only applies to tokens of four characters or more, so MCP, SK,
    and RAG are matched as themselves and never as a longer word that happens to
    start the same way.
    """
    tokens = token_texts(acronym)
    return all(len(t) < 4 for t in tokens)
