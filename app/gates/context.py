"""What every gate is handed, and how a technology's state is resolved.

A block is tokenised and alias-matched once, here, and every gate reads that one
analysis. Two gates re-tokenising the same text is how two gates end up
disagreeing about where a word starts.

Resolving a technology's state
------------------------------
An explicit ledger entry always wins, in either direction. Where there is none,
a sub-service may still be permitted by its platform: the spec's model is a
confirmed platform entry such as aws carrying a services list, with Lambda and
S3 named in it rather than as ledger entries of their own.

Every path that is not an explicit confirmation, or a service named in a
confirmed platform's list, resolves to unconfirmed. A confirmed platform with no
services list at all enumerates nothing, so it confirms no sub-service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import cached_property

from app.computed import ComputedValues
from app.errors import Rejection, Span
from app.jd import WatchList
from app.loaders import CONFIRMED, DENIED, UNCONFIRMED, Bundle, LedgerEntry
from app.models import Block
from app.normalise import (
    AliasIndex,
    AliasMatch,
    Normalised,
    Token,
    first_token_indices,
    normalise,
    sentence_ranges,
    token_texts,
    tokenise,
)

VIA_LEDGER = "ledger"
VIA_PARENT_SERVICE = "parent_service"
VIA_ABSENT = "absent"


@dataclass(frozen=True)
class TechResolution:
    """How a matched canonical id stands, and what supplies its scope."""

    canonical_id: str
    state: str
    via: str
    entry: LedgerEntry | None
    service_listed: bool | None = None

    @property
    def confirmed(self) -> bool:
        return self.state == CONFIRMED

    @property
    def denied(self) -> bool:
        return self.state == DENIED

    @property
    def depth(self) -> str | None:
        return self.entry.depth if self.entry else None

    @property
    def contexts(self) -> tuple[str, ...]:
        return self.entry.contexts if self.entry else ()


@dataclass(frozen=True)
class GateContext:
    """Loaded inputs plus the run's derived values. Never mutated by a gate."""

    bundle: Bundle
    watch: WatchList
    computed: ComputedValues
    run_date: date

    @cached_property
    def watch_index(self) -> AliasIndex:
        """The watch list as a matcher, so a multi-word posting term is found in
        output the same way a multi-word alias is."""
        by_key: dict[str, list[str]] = {}
        for term in self.watch.terms:
            by_key.setdefault(" ".join(term.key), []).append(term.surface or " ".join(term.key))
        return AliasIndex({key: [key] for key in by_key})

    def resolve(self, canonical_id: str) -> TechResolution:
        ledger = self.bundle.ledger
        explicit = ledger.get(canonical_id)
        if explicit is not None:
            return TechResolution(canonical_id, explicit.state, VIA_LEDGER, explicit)

        parent_id = self.bundle.taxonomy.parent(canonical_id)
        parent = ledger.get(parent_id) if parent_id else None
        if parent is not None and parent.confirmed:
            listed = self._service_listed(canonical_id, parent)
            state = CONFIRMED if listed else UNCONFIRMED
            return TechResolution(canonical_id, state, VIA_PARENT_SERVICE, parent, listed)

        return TechResolution(canonical_id, UNCONFIRMED, VIA_ABSENT, None)

    def _service_listed(self, canonical_id: str, parent: LedgerEntry) -> bool:
        if not parent.services:
            return False
        wanted = self.bundle.taxonomy.alias_keys(canonical_id)
        listed = {token_texts(s) for s in parent.services}
        return bool(wanted & listed)


@dataclass(frozen=True)
class MatchedTech:
    """One technology named in a block, with its resolution and its span."""

    match: AliasMatch
    resolution: TechResolution
    sentence: int

    @property
    def start(self) -> int:
        return self.match.start

    @property
    def end(self) -> int:
        return self.match.end


class BlockAnalysis:
    """One block, tokenised and alias-matched once."""

    def __init__(self, block: Block, ctx: GateContext) -> None:
        self.block = block
        self.ctx = ctx
        self.norm: Normalised = normalise(block.text, fold_case=False)
        self.tokens: tuple[Token, ...] = tokenise(self.norm)
        self.sentence_ranges = sentence_ranges(self.norm)
        self.sentence_openers = first_token_indices(self.tokens, self.sentence_ranges)

        matches = ctx.bundle.taxonomy.index.match(self.tokens)
        self.matches: tuple[MatchedTech, ...] = tuple(
            MatchedTech(m, ctx.resolve(m.canonical_id), self._sentence_of(m.tokens[0]))
            for m in matches
        )
        self.covered: frozenset[int] = frozenset(
            i for m in matches for i in m.token_indices
        )

        # The claim chain, in one place so every gate reads the same answer.
        #
        #   G0 hygiene -> numeric and version spans -> client blocklist ->
        #   taxonomy match -> proper-noun residue
        #
        # A span claimed earlier is invisible to everything later. Without an
        # order, the same characters get reported by three gates at once: a
        # blocklisted client name is also a proper noun the taxonomy has never
        # heard of, and a cited multiplier such as 3x carries both a letter and
        # a digit, which is exactly the shape the proper-noun heuristic hunts.
        #
        # Alias spans are computed before numeric spans even though the chain
        # ranks numbers first, and that is not a contradiction. Digits inside a
        # product name are part of the name, not a claim about scale: Route 53
        # and OAuth 2.0 are names. Resolving that question first is what makes
        # the rest of the chain well defined.
        #
        # A measurement label is claimed ahead of both the number gate and the
        # residue heuristic for the same reason: p95 names which measurement was
        # taken rather than how much of anything there was.
        self.label_spans: tuple[tuple[int, int], ...] = self._label_spans(ctx)
        self.label_token_indices: frozenset[int] = self._tokens_in(self.label_spans)

        self.numeric_spans: tuple[tuple[int, int], ...] = self._numeric_spans()
        self.numeric_token_indices: frozenset[int] = self._tokens_in(self.numeric_spans)

        self.client_spans: tuple[tuple[int, int], ...] = self._client_spans(ctx)
        self.client_token_indices: frozenset[int] = self._tokens_in(self.client_spans)

        self.claimed_token_indices: frozenset[int] = (
            self.covered
            | self.label_token_indices
            | self.numeric_token_indices
            | self.client_token_indices
        )

    def _tokens_in(self, spans: tuple[tuple[int, int], ...]) -> frozenset[int]:
        return frozenset(
            token.index
            for token in self.tokens
            for start, end in spans
            if token.start < end and start < token.end
        )

    def _label_spans(self, ctx: "GateContext") -> tuple[tuple[int, int], ...]:
        """Tokens naming which measurement was taken, such as p95.

        A whole-token match against an explicit allowlist, never a
        letter-then-digit rule: x1000 has exactly that shape and is a claim
        about scale. A new identifier joins the list by an edit to the policy
        file, which is a decision somebody makes rather than a pattern that
        quietly widens what the number gate cannot see.

        An alias wins over a label for the same reason it wins over a number:
        digits inside a product name belong to the name.
        """
        labels = {l.casefold() for l in ctx.bundle.policy.list_of("measurement_labels")}
        if not labels:
            return ()
        return tuple(
            (token.start, token.end)
            for token in self.tokens
            if token.index not in self.covered and token.folded in labels
        )

    def inside_a_name(self, start: int, end: int) -> bool:
        """Do these characters belong to a product name or a measurement label?

        One answer, read by the chain and by G3 alike. Two implementations of
        "is this number part of a name" is two chances to disagree about the
        same digits.
        """
        if any(m.start <= start and end <= m.end for m in self.matches):
            return True
        return any(ls <= start and end <= le for ls, le in self.label_spans)

    def _numeric_spans(self) -> tuple[tuple[int, int], ...]:
        from app.numbers import extract, word_value

        inside_a_name = self.inside_a_name

        spans: list[tuple[int, int]] = []
        for expression in extract(self.norm.text):
            start, end = self.norm.origin(expression.start, expression.end)
            if not inside_a_name(start, end):
                spans.append((start, end))
        for token in self.tokens:
            if word_value(token.folded) is None:
                continue
            if inside_a_name(token.start, token.end):
                continue
            spans.append((token.start, token.end))
        return tuple(sorted(set(spans)))

    def _client_spans(self, ctx: "GateContext") -> tuple[tuple[int, int], ...]:
        """Blocklisted client names, longest match first, non-overlapping.

        Longest first matters: with both "Northwind Retail" and "Northwind" on
        the list, the short entry would otherwise report a second time inside
        the span the long one already claimed, and the same name would be named
        twice in one report.
        """
        from app.normalise import token_texts

        blocklist = ctx.bundle.policy.list_of("client_blocklist")
        if not blocklist:
            return ()

        wanted = sorted(
            ((token_texts(name), name) for name in blocklist),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
        text_tokens = tuple(t.folded for t in self.tokens)
        taken: set[int] = set()
        spans: list[tuple[int, int]] = []

        for seq, _name in wanted:
            if not seq:
                continue
            for i in range(0, max(0, len(text_tokens) - len(seq) + 1)):
                if text_tokens[i : i + len(seq)] != seq:
                    continue
                window = self.tokens[i : i + len(seq)]
                if any(t.index in taken for t in window):
                    continue
                if any(t.index in self.numeric_token_indices for t in window):
                    continue
                taken.update(t.index for t in window)
                spans.append((window[0].start, window[-1].end))
        return tuple(sorted(spans))

    def client_name_at(self, span: tuple[int, int], ctx: "GateContext") -> str:
        from app.normalise import token_texts

        surface = self.block.text[span[0] : span[1]]
        key = token_texts(surface)
        for name in ctx.bundle.policy.list_of("client_blocklist"):
            if token_texts(name) == key:
                return name
        return surface

    def claimed_by_a_number(self, token: Token) -> bool:
        """True when a numeric expression already owns this token's span."""
        return token.index in self.numeric_token_indices

    def claimed_earlier(self, token: Token) -> bool:
        """True when anything ahead of the residue heuristic owns this token."""
        return token.index in self.claimed_token_indices

    def _sentence_of(self, token: Token) -> int:
        for i, (start, end) in enumerate(self.sentence_ranges):
            if start <= token.norm_start < end:
                return i
        return 0

    def sentence_of_token(self, token: Token) -> int:
        return self._sentence_of(token)

    def span(self, start: int, end: int) -> Span:
        return Span(start, end, self.block.text[start:end])

    def token_span(self, token: Token) -> Span:
        return self.span(token.start, token.end)

    def match_span(self, matched: MatchedTech) -> Span:
        return self.span(matched.start, matched.end)

    def whole_span(self) -> Span:
        return self.span(0, len(self.block.text))

    def reject(self, code: str, span: Span, detail: str = "", **context: str) -> Rejection:
        return Rejection(
            code=code,
            span=span,
            detail=detail,
            block_id=self.block.block_id,
            context=dict(context),
        )


__all__ = [
    "BlockAnalysis",
    "GateContext",
    "MatchedTech",
    "TechResolution",
    "VIA_ABSENT",
    "VIA_LEDGER",
    "VIA_PARENT_SERVICE",
    "CONFIRMED",
    "DENIED",
    "UNCONFIRMED",
]
