"""G2, the scope gate. Pure function. No model call, no network.

Depth, context, services, exposure, and cohabitation.

Cohabitation is the check that per-technology context cannot make. Two
technologies can each be confirmed, each under a role of its own, and still
produce a sentence describing work that never happened by sitting next to each
other. So the technologies sharing a sentence must share a role, and inside a
bullet that shared role must be the bullet's own.

Context is not checked on the summary or the skills section: neither sits under
a role, so there is no role to check against. Depth, services, and cohabitation
still apply there, and G1 has already bounded what may appear at all.

A free-text scope such as "producer side only" cannot be enforced in code. The
entry's scope_note is surfaced for the Step 4 review instead, by scope_notes().
"""

from __future__ import annotations

from app.errors import GateResult, Rejection
from app.gates.context import BlockAnalysis, GateContext, MatchedTech
from app.models import BULLET, CLAIM_BLOCKS
from app.normalise import normalise_spelling


def check(analysis: BlockAnalysis, ctx: GateContext) -> GateResult:
    if analysis.block.block_type not in CLAIM_BLOCKS:
        return GateResult()

    rejections: list[Rejection] = []
    rejections.extend(_depth(analysis, ctx))
    rejections.extend(_services(analysis, ctx))
    rejections.extend(_exposure(analysis))
    if analysis.block.block_type == BULLET:
        rejections.extend(_context(analysis))
    rejections.extend(_cohabitation(analysis))
    return GateResult(tuple(rejections))


def _build_verb_tokens(analysis: BlockAnalysis, ctx: GateContext):
    lexicon = ctx.bundle.lexicon
    build_verbs = {
        normalise_spelling(v, lexicon.spelling_variants)
        for v in ctx.bundle.policy.list_of("build_verbs")
    }
    for token in analysis.tokens:
        if lexicon.spell(token.folded) in build_verbs:
            yield token


def _depth(analysis: BlockAnalysis, ctx: GateContext):
    verbs = tuple(_build_verb_tokens(analysis, ctx))
    if not verbs:
        return
    for matched in analysis.matches:
        resolution = matched.resolution
        if not resolution.confirmed or resolution.depth == "built":
            continue
        verb = verbs[0]
        yield analysis.reject(
            "SCOPE_DEPTH",
            analysis.match_span(matched),
            f"{verb.raw!r} is a build verb but {resolution.canonical_id} has depth "
            f"{resolution.depth!r}",
            canonical_id=resolution.canonical_id,
            verb=verb.raw,
            depth=str(resolution.depth),
        )


def _context(analysis: BlockAnalysis):
    role_id = analysis.block.role_id or ""
    for matched in analysis.matches:
        resolution = matched.resolution
        if not resolution.confirmed:
            continue
        if not resolution.contexts:
            continue
        if role_id in resolution.contexts:
            continue
        yield analysis.reject(
            "SCOPE_CONTEXT",
            analysis.match_span(matched),
            f"{resolution.canonical_id} is confirmed under "
            f"{', '.join(resolution.contexts)} but this bullet is under {role_id!r}",
            canonical_id=resolution.canonical_id,
            role_id=role_id,
        )


def _services(analysis: BlockAnalysis, ctx: GateContext):
    for matched in analysis.matches:
        resolution = matched.resolution
        if resolution.service_listed is not False:
            continue
        parent = resolution.entry
        listed = ", ".join(parent.services) if parent and parent.services else "(none listed)"
        yield analysis.reject(
            "SCOPE_SERVICE",
            analysis.match_span(matched),
            f"{ctx.bundle.taxonomy.display(resolution.canonical_id)} is not in the "
            f"services list of {parent.canonical_id if parent else 'its platform'}: {listed}",
            canonical_id=resolution.canonical_id,
            platform=parent.canonical_id if parent else "",
        )


def _exposure(analysis: BlockAnalysis):
    if analysis.block.block_type != BULLET:
        return
    for matched in analysis.matches:
        resolution = matched.resolution
        if resolution.confirmed and resolution.depth == "exposure":
            yield analysis.reject(
                "SCOPE_EXPOSURE_IN_BULLET",
                analysis.match_span(matched),
                f"{resolution.canonical_id} has depth exposure, which may appear only "
                f"on a separate environment line",
                canonical_id=resolution.canonical_id,
            )


def _cohabitation(analysis: BlockAnalysis):
    by_sentence: dict[int, list[MatchedTech]] = {}
    for matched in analysis.matches:
        if not matched.resolution.confirmed or not matched.resolution.contexts:
            continue
        by_sentence.setdefault(matched.sentence, []).append(matched)

    role_id = analysis.block.role_id if analysis.block.block_type == BULLET else None

    for sentence, group in sorted(by_sentence.items()):
        # One technology cannot cohabit with anything. Without this guard a
        # single technology under the wrong role reported both SCOPE_CONTEXT and
        # SCOPE_COHABITATION, which is the same finding named twice.
        if len(group) < 2:
            continue
        shared: set[str] | None = None
        for matched in group:
            contexts = set(matched.resolution.contexts)
            shared = contexts if shared is None else (shared & contexts)
        if shared is None:
            continue

        start = min(m.start for m in group)
        end = max(m.end for m in group)
        names = ", ".join(sorted({m.resolution.canonical_id for m in group}))

        if not shared:
            yield analysis.reject(
                "SCOPE_COHABITATION",
                analysis.span(start, end),
                f"{names} share a sentence but no role, so the sentence blends work "
                f"from different roles",
                sentence=str(sentence),
                canonical_ids=names,
            )
        elif role_id is not None and role_id not in shared:
            yield analysis.reject(
                "SCOPE_COHABITATION",
                analysis.span(start, end),
                f"{names} share {', '.join(sorted(shared))} but not this bullet's role "
                f"{role_id!r}",
                sentence=str(sentence),
                canonical_ids=names,
                role_id=role_id,
            )


def scope_notes(analysis: BlockAnalysis, ctx: GateContext) -> tuple[tuple[str, str], ...]:
    """Scope notes for the technologies a block names, for Step 4's review.

    A note such as "producer side only" is free text. No gate can enforce it, so
    it is shown next to the bullet and a human decides. Returned rather than
    raised, because a note is not a rejection.
    """
    out: list[tuple[str, str]] = []
    for matched in analysis.matches:
        entry = matched.resolution.entry
        if entry and entry.scope_note and matched.resolution.confirmed:
            out.append((matched.resolution.canonical_id, entry.scope_note))
    return tuple(dict.fromkeys(out))
