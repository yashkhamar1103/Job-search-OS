"""Extracting and canonicalising numeric expressions.

Shared by G3 and by the metric parser, so a bullet's number and the metric it
cites are read by exactly the same code. Two parsers would be two chances to
decide that 2.5M and 2,500,000 are different numbers.

Every expression canonicalises to a kind and a value. The kind is part of the
identity: 40 and 40% and 40x are three different claims, and a metric recording
one does not support another. A trailing plus is its own kind too, because a
metric of 50 does not support a claim of 50 or more.

A magnitude is multiplied out, so 2.5M and 2,500,000 canonicalise identically.
A vague magnitude word such as hundreds carries no value to multiply out, so it
canonicalises to itself and can only ever match a metric that says the same
word. That is deliberate: it fails closed rather than quietly matching 100.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

KIND_PLAIN = "plain"
KIND_PERCENT = "percent"
KIND_CURRENCY = "currency"
KIND_MULTIPLIER = "multiplier"
KIND_RANGE = "range"
KIND_WORD = "word"

_MAGNITUDES = {
    "k": Decimal(1_000),
    "thousand": Decimal(1_000),
    "m": Decimal(1_000_000),
    "mn": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "b": Decimal(1_000_000_000),
    "bn": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
}

#: Number words the spec requires extracting, two through twenty.
NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}

#: Magnitude words with no definite value. They imply a number that does not
#: exist, so they only ever match a metric using the same word.
VAGUE_MAGNITUDE_WORDS = frozenset({"dozens", "hundreds", "thousands", "millions", "dozen"})

_NUM = r"\d[\d,]*(?:\.\d+)?"
_MAG = r"k|mn|m|bn|b|thousand|million|billion"

_EXPRESSION_RE = re.compile(
    rf"""
    (?P<currency>[$€£]\s?{_NUM}(?:\s?(?:{_MAG})\b)?\+?)
  | (?P<range>{_NUM}\s?(?:to|-|–)\s?{_NUM}\s?%?)
  | (?P<percent>{_NUM}\s?%\+?)
  | (?P<multiplier>{_NUM}\s?x\b\+?)
  | (?P<magnitude>{_NUM}\s?(?:{_MAG})\b\+?)
  | (?P<plain>{_NUM}\+?)
    """,
    re.IGNORECASE | re.VERBOSE,
)

_TRAILING_MAG_RE = re.compile(rf"({_NUM})\s?({_MAG})?\+?$", re.IGNORECASE)


def _canonical_text(value) -> str:
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, tuple):
        return "|".join(_canonical_text(v) for v in value)
    return str(value)


@dataclass(frozen=True)
class NumericValue:
    """A canonicalised numeric expression."""

    kind: str
    value: Decimal | str | tuple[Decimal, Decimal]
    symbol: str = ""
    plus: bool = False
    """A trailing plus. Part of the identity on every kind, not just plain
    numbers: a metric of 40% supports a claim of 40%, and does not support a
    claim of 40% or more."""

    def key(self) -> tuple:
        """The identity used for comparison.

        Decimals are normalised before stringifying, so 2.5M scaling to
        2500000.0 and a literal 2,500,000 produce the same key. Without this
        they differ by a trailing zero and a metric would fail to support the
        bullet that cites it.
        """
        return (self.kind, self.symbol, _canonical_text(self.value), self.plus)


@dataclass(frozen=True)
class NumericExpression:
    """A canonicalised value plus where it was found, in normalised offsets."""

    canonical: NumericValue
    start: int
    end: int
    raw: str

    @property
    def key(self) -> tuple:
        return self.canonical.key()


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _scaled(text: str) -> Decimal | None:
    """Parse a number with an optional magnitude suffix, multiplied out."""
    match = _TRAILING_MAG_RE.search(text.strip())
    if not match:
        return None
    base = _decimal(match.group(1))
    if base is None:
        return None
    suffix = (match.group(2) or "").lower()
    if suffix:
        base *= _MAGNITUDES[suffix]
    return base


def _canonicalise(group: str, text: str) -> NumericValue | None:
    body = text.strip()
    plus = body.endswith("+")
    if plus and group != "range":
        body = body[:-1].strip()

    if group == "currency":
        symbol = body[0]
        amount = _scaled(body[1:])
        return NumericValue(KIND_CURRENCY, amount, symbol, plus) if amount is not None else None
    if group == "range":
        is_percent = body.rstrip().endswith("%")
        parts = re.split(r"\s?(?:to|-|–)\s?", body.rstrip("%").strip(), maxsplit=1)
        if len(parts) != 2:
            return None
        low, high = _decimal(parts[0]), _decimal(parts[1])
        if low is None or high is None:
            return None
        kind = KIND_RANGE
        return NumericValue(kind, (low, high), "%" if is_percent else "")
    if group == "percent":
        amount = _decimal(body.rstrip("% "))
        return NumericValue(KIND_PERCENT, amount, "", plus) if amount is not None else None
    if group == "multiplier":
        amount = _decimal(body.rstrip("xX "))
        return NumericValue(KIND_MULTIPLIER, amount, "", plus) if amount is not None else None
    if group == "magnitude":
        amount = _scaled(body)
        return NumericValue(KIND_PLAIN, amount, "", plus) if amount is not None else None
    if group == "plain":
        amount = _decimal(body)
        return NumericValue(KIND_PLAIN, amount, "", plus) if amount is not None else None
    return None


def extract(text: str) -> tuple[NumericExpression, ...]:
    """Every numeric expression in `text`, with offsets into `text`.

    Digit-bearing expressions only. Number words are handled by
    `word_value`, because they are found on the token stream where whole-word
    matching is already guaranteed.
    """
    out: list[NumericExpression] = []
    for match in _EXPRESSION_RE.finditer(text):
        group = match.lastgroup
        if group is None:
            continue
        canonical = _canonicalise(group, match.group(group))
        if canonical is None:
            continue
        out.append(NumericExpression(canonical, match.start(), match.end(), match.group(0)))
    return tuple(out)


def word_value(token_text: str) -> NumericValue | None:
    """Canonicalise a number word, or None when the token is not one."""
    lowered = token_text.lower()
    if lowered in NUMBER_WORDS:
        return NumericValue(KIND_PLAIN, Decimal(NUMBER_WORDS[lowered]))
    if lowered in VAGUE_MAGNITUDE_WORDS:
        return NumericValue(KIND_WORD, lowered)
    return None


def supported_keys(metric_values: list[str]) -> frozenset[tuple]:
    """Every canonical key the given metric values support.

    Metric values are read with the same extractor as bullet text, so a metric
    recorded as 2.5M supports a bullet saying 2,500,000 and vice versa.
    """
    keys: set[tuple] = set()
    for value in metric_values:
        for expression in extract(value):
            keys.add(expression.key)
        for word in re.findall(r"[a-z]+", value.lower()):
            canonical = word_value(word)
            if canonical is not None:
                keys.add(canonical.key())
    return frozenset(keys)
