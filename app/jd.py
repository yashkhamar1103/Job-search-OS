"""The job description watch list, built deterministically.

The job description is where fabrications come from. A term that appears in the
posting and then appears in the CV, without appearing anywhere in the evidence,
is the exact shape of the failure this system exists to prevent, so the watch
list is built here in code before any model sees the posting.

A model call may also extract terms from the posting. Its output can only be
added to this list. Nothing a model returns can remove a term from it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.loaders import Bundle
from app.normalise import (
    first_token_indices,
    ngrams,
    normalise,
    proper_noun_signal,
    sentence_ranges,
    token_texts,
    tokenise,
)


@dataclass(frozen=True)
class WatchTerm:
    """One term the CV must be able to justify if it uses it."""

    tokens: tuple[str, ...]
    surface: str
    canonical_id: str | None
    source: str
    """taxonomy, camel_case, symbol_or_digit, capitalised, or model."""

    from_stripped_span: bool = False
    """True when this term was extracted from a span an invisible character was
    removed from. The posting is not rejected for carrying one, because Yash did
    not write the posting, but a term that arrived altered is worth knowing
    about before it is treated as a requirement."""

    @property
    def key(self) -> tuple[str, ...]:
        return self.tokens


@dataclass(frozen=True)
class WatchList:
    terms: tuple[WatchTerm, ...] = ()
    copy_ngrams: frozenset[tuple[str, ...]] = frozenset()
    ngram_size: int = 8
    hygiene: object | None = None
    """What sanitising the posting removed, for the run report."""

    @property
    def report_lines(self) -> tuple[str, ...]:
        if self.hygiene is None:
            return ()
        lines = list(self.hygiene.report_lines())
        lines.extend(
            f"job description: term {t.surface!r} was extracted from an altered span"
            for t in self.terms
            if t.from_stripped_span
        )
        return tuple(lines)

    @property
    def keys(self) -> frozenset[tuple[str, ...]]:
        return frozenset(t.key for t in self.terms)

    def by_key(self) -> dict[tuple[str, ...], WatchTerm]:
        out: dict[tuple[str, ...], WatchTerm] = {}
        for term in self.terms:
            out.setdefault(term.key, term)
        return out

    def extended_with_model_terms(self, terms: list[str]) -> "WatchList":
        """Add model-extracted terms. Add only, never remove.

        Milestone 2 calls this with the model's extraction. Being additive by
        construction is why a model cannot shrink the defence.
        """
        existing = self.by_key()
        extra: list[WatchTerm] = []
        for surface in terms:
            key = token_texts(surface)
            if not key or key in existing:
                continue
            term = WatchTerm(key, surface, None, "model")
            existing[key] = term
            extra.append(term)
        return WatchList(
            self.terms + tuple(extra), self.copy_ngrams, self.ngram_size, self.hygiene
        )


def _overlaps(term: WatchTerm, spans: tuple[tuple[int, int], ...], text: str) -> bool:
    """True when the term's surface sits inside a span that was stripped."""
    at = text.find(term.surface)
    if at < 0:
        return False
    end = at + len(term.surface)
    return any(at < span_end and span_start < end for span_start, span_end in spans)


@dataclass(frozen=True)
class TaxonomyCandidate:
    surface: str
    signal: str


@dataclass(frozen=True)
class TaxonomyCandidates:
    """Unknown terms from the posting, for review/taxonomy_candidates.json.

    These go to Yash. They never go into the ledger, and nothing in the app
    writes them into the taxonomy either.
    """

    terms: tuple[TaxonomyCandidate, ...] = ()

    def to_json(self) -> dict:
        return {
            "schema_version": 1,
            "_note": (
                "Terms found in a job description that the taxonomy does not know. "
                "For Yash to triage by hand. Nothing in the app writes to the "
                "taxonomy or the ledger."
            ),
            "candidates": [{"term": t.surface, "signal": t.signal} for t in self.terms],
        }


def build_watch_list(
    jd_text: str, bundle: Bundle
) -> tuple[WatchList, TaxonomyCandidates]:
    """Build the watch list and the unknown-term review list from a posting.

    The posting is sanitised, never rejected. G0 rejects generated text that
    carries an invisible character; a posting is an input from outside and Yash
    does not control what a recruiter pasted into it. What was removed is
    recorded for the run report, and any term drawn from a span that was
    stripped is flagged.
    """
    from app.gates.g0_hygiene import sanitise_jd

    hygiene = sanitise_jd(jd_text)
    jd_text = hygiene.text
    norm = normalise(jd_text, fold_case=False)
    tokens = tokenise(norm)
    ranges = sentence_ranges(norm)
    sentence_openers = first_token_indices(tokens, ranges)

    terms: dict[tuple[str, ...], WatchTerm] = {}
    candidates: list[TaxonomyCandidate] = []
    covered: set[int] = set()

    for match in bundle.taxonomy.index.match(tokens):
        covered.update(match.token_indices)
        surface = jd_text[match.start : match.end]
        key = tuple(t.folded for t in match.tokens)
        terms.setdefault(key, WatchTerm(key, surface, match.canonical_id, "taxonomy"))

        # Every other spelling of the same product goes on the list too. A
        # posting saying Apache Kafka and a CV saying Kafka are the same term,
        # and watching only the posting's spelling would miss the CV's.
        for alias in bundle.taxonomy.aliases(match.canonical_id):
            alias_key = token_texts(alias)
            if alias_key:
                terms.setdefault(
                    alias_key, WatchTerm(alias_key, alias, match.canonical_id, "taxonomy")
                )

    for token in tokens:
        if token.index in covered:
            continue
        signal = proper_noun_signal(
            token,
            sentence_initial=token.index in sentence_openers,
            wordlist=bundle.lexicon.wordlist,
        )
        if signal is None:
            continue
        key = (token.folded,)
        if key in terms:
            continue
        terms[key] = WatchTerm(key, token.raw, None, signal)
        candidates.append(TaxonomyCandidate(token.raw, signal))

    ngram_size = int(bundle.policy["jd_copy_ngram"])
    copy_ngrams = frozenset(gram for gram, _, _ in ngrams(tokens, ngram_size))

    if hygiene.altered_spans:
        terms = {
            key: (
                term
                if not _overlaps(term, hygiene.altered_spans, jd_text)
                else WatchTerm(term.tokens, term.surface, term.canonical_id, term.source, True)
            )
            for key, term in terms.items()
        }

    seen_surface: dict[str, TaxonomyCandidate] = {}
    for candidate in candidates:
        seen_surface.setdefault(candidate.surface, candidate)

    return (
        WatchList(tuple(terms.values()), copy_ngrams, ngram_size, hygiene),
        TaxonomyCandidates(tuple(seen_surface.values())),
    )
