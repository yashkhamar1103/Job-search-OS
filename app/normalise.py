"""Shared text normalisation, tokenisation, and alias matching.

Every gate reads text through this module so that one spelling of a rule cannot
pass in one gate and fail in another.

Normalisation is character by character, and every normalised character carries
the index of the original character that produced it. That is what lets a
rejection point at a span in Yash's untouched text rather than at an offset in
some internal string he never sees.

Two deliberate departures from a plain NFKC fold, both of which tighten
matching rather than loosen it:

  1. Decomposition, then combining marks removed, then recomposition. A plain
     NFKC leaves a precomposed accent intact and leaves a decomposed one as two
     characters, so the same word written two ways would match a technology
     alias only once. Folding both to the base letter closes that gap.

  2. Format characters are dropped. A zero width space or a soft hyphen placed
     inside a technology name would otherwise hide it from every gate.

Neither changes a threshold. Both make evasion harder.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

# Characters kept inside a token so that .NET, C#, C++, Node.js, and CI/CD
# survive tokenisation as single tokens.
TOKEN_INNER = ".#+/"

_TOKEN_RE = re.compile(r"[0-9A-Za-z" + re.escape(TOKEN_INNER) + r"]+")

# Stripped from a token's edges. A trailing # or + is meaningful (C#, C++) and a
# leading . is meaningful (.NET), so those are not stripped.
_LEAD_STRIP = "#+/"
_TRAIL_STRIP = "./"

_SENTENCE_END_RE = re.compile(r"([.!?]+)(\s+)")

# Abbreviations whose trailing period does not end a sentence.
_ABBREVIATIONS = frozenset(
    {
        "e.g.",
        "i.e.",
        "etc.",
        "vs.",
        "inc.",
        "ltd.",
        "llc.",
        "co.",
        "dr.",
        "mr.",
        "ms.",
        "mrs.",
        "st.",
        "approx.",
        "no.",
    }
)


@dataclass(frozen=True)
class Normalised:
    """Normalised text plus a map back to the original string."""

    text: str
    offsets: tuple[int, ...]
    original: str
    folded: bool

    def origin(self, start: int, end: int) -> tuple[int, int]:
        """Translate a half-open range in `text` to one in `original`."""
        if start >= end:
            raise ValueError("empty range has no origin")
        return self.offsets[start], self.offsets[end - 1] + 1

    def raw(self, start: int, end: int) -> str:
        o_start, o_end = self.origin(start, end)
        return self.original[o_start:o_end]


@dataclass(frozen=True)
class Token:
    """One token, positioned in both the normalised and the original text."""

    text: str
    """The token as normalised. Lowercase when the source was case folded."""

    folded: str
    """The token case folded, always. Matching uses this, the proper-noun
    heuristic uses `raw`, and both come from one tokenisation, so a cased and a
    folded token stream can never drift out of alignment with each other."""

    start: int
    """Start index in the original text."""

    end: int
    """End index in the original text."""

    norm_start: int
    norm_end: int
    index: int
    """Position of this token in its block's token sequence."""

    raw: str
    """The original slice, casing and all."""


def normalise(text: str, *, fold_case: bool = True) -> Normalised:
    """Normalise `text`, collapsing whitespace and keeping an offset map.

    With `fold_case` false, casing is preserved. The proper-noun heuristic and
    sentence splitting need capitals, so they run over the unfolded form.
    """
    out: list[str] = []
    offsets: list[int] = []
    pending_space_at: int | None = None
    started = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch.isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            if started:
                pending_space_at = i
            i = j
            continue

        piece = unicodedata.normalize("NFKD", ch)
        piece = "".join(c for c in piece if unicodedata.category(c) not in ("Mn", "Mc", "Me", "Cf"))
        if fold_case:
            piece = piece.casefold()
        piece = unicodedata.normalize("NFKC", piece)

        if not piece:
            # The character was purely a combining mark or a format character.
            # It contributes nothing and must not split a token.
            i += 1
            continue

        if pending_space_at is not None:
            out.append(" ")
            offsets.append(pending_space_at)
            pending_space_at = None

        for c in piece:
            out.append(c)
            offsets.append(i)
        started = True
        i += 1

    return Normalised("".join(out), tuple(offsets), text, fold_case)


def _trim(tok: str) -> tuple[str, int]:
    """Trim a token's edges. Returns the token and how many chars came off the
    front, so offsets stay correct."""
    lead = 0
    while tok and tok[0] in _LEAD_STRIP:
        tok = tok[1:]
        lead += 1
    while tok and tok[-1] in _TRAIL_STRIP:
        tok = tok[:-1]
    return tok, lead


def tokenise(norm: Normalised) -> tuple[Token, ...]:
    """Split normalised text into tokens positioned in the original string."""
    tokens: list[Token] = []
    for match in _TOKEN_RE.finditer(norm.text):
        raw_tok = match.group(0)
        trimmed, lead = _trim(raw_tok)
        if not trimmed:
            continue
        ns = match.start() + lead
        ne = ns + len(trimmed)
        o_start, o_end = norm.origin(ns, ne)
        folded = trimmed if norm.folded else normalise(trimmed, fold_case=True).text
        tokens.append(
            Token(
                text=trimmed,
                folded=folded,
                start=o_start,
                end=o_end,
                norm_start=ns,
                norm_end=ne,
                index=len(tokens),
                raw=norm.original[o_start:o_end],
            )
        )
    return tuple(tokens)


def tokens_of(text: str, *, fold_case: bool = True) -> tuple[Token, ...]:
    return tokenise(normalise(text, fold_case=fold_case))


def token_texts(text: str) -> tuple[str, ...]:
    """The folded token sequence of a string. The canonical key for a term."""
    return tuple(t.folded for t in tokens_of(text))


# ---------------------------------------------------------------------------
# Spelling
# ---------------------------------------------------------------------------

_ISE_RE = re.compile(r"is(e|es|ed|ing|ation|ations)$")
_YSE_RE = re.compile(r"ys(e|es|ed|ing)$")


def normalise_spelling(token: str, variants: Mapping[str, str] | None = None) -> str:
    """Fold British and American spellings to one matching form.

    The -ise and -yse rules are applied to both the config entry and the input,
    so an over-eager fold (rise becoming rize) cannot cause a mismatch. It could
    in principle collide two distinct words, which is why irregular pairs such
    as modelled and modeled are handled by the explicit variants map instead of
    by a doubled-consonant rule, where filled and filed would collide.
    """
    tok = token
    if variants:
        tok = variants.get(tok, tok)
    tok = _ISE_RE.sub(r"iz\1", tok)
    tok = _YSE_RE.sub(r"yz\1", tok)
    if variants:
        tok = variants.get(tok, tok)
    return tok


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------


def sentence_ranges(norm: Normalised) -> tuple[tuple[int, int], ...]:
    """Split normalised text into sentence ranges, deterministically.

    A break needs terminal punctuation followed by whitespace, so Node.js and
    3.5 never split. A short abbreviation list covers the remaining cases.
    """
    if not norm.text:
        return ()

    ranges: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_END_RE.finditer(norm.text):
        end = match.end(1)
        tail = norm.text[max(0, end - 12) : end].lower()
        if any(tail.endswith(abbr) for abbr in _ABBREVIATIONS):
            continue
        ranges.append((start, end))
        start = match.end(2)
    if start < len(norm.text):
        ranges.append((start, len(norm.text)))
    return tuple(ranges)


def sentence_index(ranges: Sequence[tuple[int, int]], norm_pos: int) -> int:
    for i, (start, end) in enumerate(ranges):
        if start <= norm_pos < end:
            return i
    return max(0, len(ranges) - 1)


# ---------------------------------------------------------------------------
# Alias matching
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AliasMatch:
    canonical_id: str
    alias: str
    tokens: tuple[Token, ...]

    @property
    def start(self) -> int:
        return self.tokens[0].start

    @property
    def end(self) -> int:
        return self.tokens[-1].end

    @property
    def text(self) -> str:
        return " ".join(t.folded for t in self.tokens)

    @property
    def token_indices(self) -> tuple[int, ...]:
        return tuple(t.index for t in self.tokens)


def _plural_forms_match(text_tok: str, alias_tok: str) -> bool:
    """Tolerate a plural on either side. Only for tokens long enough that the
    tolerance cannot turn a short acronym into a different one."""
    if len(alias_tok) < 4 and len(text_tok) < 4:
        return False
    for shorter, longer in ((alias_tok, text_tok), (text_tok, alias_tok)):
        if len(shorter) < 4:
            continue
        if longer == shorter + "s" or longer == shorter + "es":
            return True
        if shorter.endswith("y") and longer == shorter[:-1] + "ies":
            return True
    return False


def _tokens_equal(text_tok: str, alias_tok: str, *, allow_plural: bool) -> bool:
    if text_tok == alias_tok:
        return True
    return allow_plural and _plural_forms_match(text_tok, alias_tok)


class AliasIndex:
    """Longest-first, non-overlapping alias matcher over a token sequence.

    Hyphenation needs no special case: a hyphen is not a token character, so
    retrieval-augmented and retrieval augmented tokenise identically on both the
    alias side and the text side.
    """

    def __init__(self, aliases_by_id: Mapping[str, Iterable[str]]) -> None:
        self._entries: list[tuple[tuple[str, ...], str, str]] = []
        self._by_alias: dict[str, str] = {}
        for canonical_id, aliases in aliases_by_id.items():
            for alias in aliases:
                seq = token_texts(alias)
                if not seq:
                    continue
                self._entries.append((seq, canonical_id, alias))
                self._by_alias.setdefault(" ".join(seq), canonical_id)
        # Longest alias wins, so Azure AI Search is never matched as Azure.
        self._entries.sort(key=lambda e: (len(e[0]), sum(len(t) for t in e[0])), reverse=True)
        self._max_len = max((len(e[0]) for e in self._entries), default=0)
        self._first_token: dict[str, list[int]] = {}
        for i, (seq, _, _) in enumerate(self._entries):
            self._first_token.setdefault(seq[0], []).append(i)
        # Plural tolerance means a text token may not equal the alias's first
        # token literally, so a first-token bucket alone would miss matches on
        # single-token aliases. Those are cheap to scan, so keep a flat list of
        # short-sequence entries for the fallback pass.
        self._fallback = [i for i, (seq, _, _) in enumerate(self._entries) if len(seq) == 1]

    @property
    def alias_count(self) -> int:
        return len(self._entries)

    def resolve(self, alias: str) -> str | None:
        """Resolve a single alias string to a canonical id, exactly."""
        return self._by_alias.get(" ".join(token_texts(alias)))

    def _candidates(self, token: Token) -> list[int]:
        seen = self._first_token.get(token.folded, [])
        if seen:
            return sorted(set(seen) | set(self._fallback))
        return self._fallback

    def match(self, tokens: Sequence[Token]) -> tuple[AliasMatch, ...]:
        out: list[AliasMatch] = []
        i = 0
        n = len(tokens)
        while i < n:
            best: tuple[int, str, str] | None = None
            for idx in self._candidates(tokens[i]):
                seq, canonical_id, alias = self._entries[idx]
                length = len(seq)
                if i + length > n:
                    continue
                if best is not None and length < best[0]:
                    continue
                ok = True
                for k, alias_tok in enumerate(seq):
                    allow_plural = k == length - 1
                    if not _tokens_equal(tokens[i + k].folded, alias_tok, allow_plural=allow_plural):
                        ok = False
                        break
                if ok and (best is None or length > best[0]):
                    best = (length, canonical_id, alias)
            if best is not None:
                length, canonical_id, alias = best
                out.append(AliasMatch(canonical_id, alias, tuple(tokens[i : i + length])))
                i += length
            else:
                i += 1
        return tuple(out)


# ---------------------------------------------------------------------------
# Proper-noun heuristic
# ---------------------------------------------------------------------------

_CAMEL_RE = re.compile(r"[a-z][A-Z]|[A-Z]{2,}[a-z]")
_HAS_LETTER_RE = re.compile(r"[A-Za-z]")
_HAS_DIGIT_RE = re.compile(r"[0-9]")


def proper_noun_signal(
    token: Token,
    *,
    sentence_initial: bool,
    wordlist: frozenset[str],
) -> str | None:
    """Which proper-noun signal a token fires, or None.

    Callers that only need a yes or no use is_proper_noun_shaped. The signal
    name is what the review file records, so Yash can see why a term was
    flagged without rerunning anything.

    Three signals, taken from the JD candidate rules in the spec:

      CamelCase, which ordinary prose does not produce.
      A token mixing letters with . # + / or digits, such as S3 or Log4j.
      A mid-sentence capital on a word that is not ordinary English.

    A token of digits alone is excluded on purpose. Every number in a bullet
    would otherwise become a watch-list term, and G3 would then be competing
    with G1 over the same numbers while a truthful cited metric that also
    appears in the job description got rejected for being copied.
    """
    text = token.raw
    if not text or not _HAS_LETTER_RE.search(text):
        return None
    if _CAMEL_RE.search(text):
        return "camel_case"
    if _HAS_DIGIT_RE.search(text) or any(c in TOKEN_INNER for c in text):
        return "symbol_or_digit"
    if text[0].isupper() and not sentence_initial and token.folded not in wordlist:
        return "capitalised"
    return None


def is_proper_noun_shaped(
    token: Token,
    *,
    sentence_initial: bool,
    wordlist: frozenset[str],
) -> bool:
    return (
        proper_noun_signal(token, sentence_initial=sentence_initial, wordlist=wordlist)
        is not None
    )


def ngrams(tokens: Sequence[Token], size: int) -> Iterable[tuple[tuple[str, ...], Token, Token]]:
    """Yield (gram, first_token, last_token) for every window of `size`."""
    if size <= 0:
        return
    for i in range(0, max(0, len(tokens) - size + 1)):
        window = tokens[i : i + size]
        yield tuple(t.folded for t in window), window[0], window[-1]


def first_token_indices(
    tokens: Sequence[Token], ranges: Sequence[tuple[int, int]]
) -> frozenset[int]:
    """Indices of the tokens that open a sentence.

    A sentence may open with punctuation or a quote, so the opening token is the
    first token inside the range rather than the token sitting exactly on the
    range's start offset.
    """
    firsts: set[int] = set()
    for start, end in ranges:
        for token in tokens:
            if token.norm_start >= start and token.norm_end <= end:
                firsts.add(token.index)
                break
    return frozenset(firsts)
