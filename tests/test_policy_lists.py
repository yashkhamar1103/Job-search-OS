"""The policy lists as data: no duplicates, no contradictions, one spelling.

These are not gate tests. They check the config the gates read, because a list
that contradicts itself produces a gate that contradicts itself, and the failure
shows up as a mysterious rejection rather than as a bad line in a JSON file.
"""

from __future__ import annotations

import re

import pytest

from tests.conftest import assert_does_not_reject, bullet

#: The four endings normalise_spelling folds, in both directions.
_FOLDS = (
    (re.compile(r"is(e|es|ed|ing|ation|ations)$"), r"iz\1"),
    (re.compile(r"iz(e|es|ed|ing|ation|ations)$"), r"is\1"),
    (re.compile(r"ys(e|es|ed|ing)$"), r"yz\1"),
    (re.compile(r"yz(e|es|ed|ing)$"), r"ys\1"),
)


def _counterpart(word: str) -> str | None:
    """The other spelling of a word, or None when it has only one."""
    for pattern, replacement in _FOLDS:
        if pattern.search(word):
            return pattern.sub(replacement, word)
    return None


def _policy_list(key: str) -> list[str]:
    from app.loaders import ROOT, load_policy

    return list(load_policy(ROOT / "config" / "policy.json").list_of(key))


OPENING_VERBS = _policy_list("opening_verbs")
SPELLING_PAIRS = [(v, _counterpart(v)) for v in OPENING_VERBS if _counterpart(v)]


def test_the_opening_verb_list_actually_contains_both_spelling_shapes():
    """Guards the parametrisation below from silently covering nothing."""
    assert len(SPELLING_PAIRS) >= 10, [v for v, _ in SPELLING_PAIRS]


@pytest.mark.parametrize("listed,other", SPELLING_PAIRS, ids=lambda v: v)
def test_both_spellings_of_an_opening_verb_resolve_to_the_one_entry(listed, other, ctx):
    """F3. One config line covers -ise and -ize.

    Asserted through the gate rather than through the folding function, because
    the claim worth making is about what happens to a bullet. Folding both sides
    with the same function and comparing them would be true by construction and
    would still leave the gate free to be wrong.
    """
    for spelling in (listed, other):
        block = bullet(f"{spelling.capitalize()} the ingestion path for order events.")
        assert_does_not_reject(block, ctx, "OPENING_VERB_UNLISTED", "WEAK_OPENING")


def test_no_two_opening_verbs_fold_to_the_same_entry(bundle):
    """Two entries that fold together are one entry written twice, and the
    second one is dead config that reads as coverage."""
    seen: dict[str, str] = {}
    for verb in OPENING_VERBS:
        key = " ".join(bundle.lexicon.spell(t) for t in verb.lower().split())
        assert key not in seen, f"{verb!r} and {seen[key]!r} are the same entry"
        seen[key] = verb


@pytest.mark.parametrize(
    "key",
    [
        "build_verbs", "weak_openers", "opening_verbs", "be_have_openers",
        "banned_phrases", "vague_intensity_words", "proficiency_qualifiers",
        "duration_hedges", "ambiguous_acronyms", "unverifiable_labels",
        "title_nouns", "title_modifiers", "leading_hedges", "trailing_hedges",
        "vague_quantifiers", "location_allowlist",
    ],
)
def test_no_list_repeats_an_entry(key):
    entries = _policy_list(key)
    duplicates = sorted({e for e in entries if entries.count(e) > 1})
    assert not duplicates, f"{key} repeats {duplicates}"


def test_no_verb_is_both_an_opener_to_use_and_an_opener_to_avoid(bundle):
    """A verb on both lists would be rejected and then reported as unlisted,
    which is a config contradiction wearing two gate codes."""
    spell = lambda phrase: " ".join(  # noqa: E731
        bundle.lexicon.spell(t) for t in phrase.lower().split()
    )
    openers = {spell(v) for v in OPENING_VERBS}
    weak = {spell(v) for v in _policy_list("weak_openers")}
    banned = {spell(v) for v in _policy_list("banned_phrases")}
    assert not openers & weak, sorted(openers & weak)
    assert not openers & banned, sorted(openers & banned)


def test_every_build_verb_is_also_an_opening_verb(bundle):
    """A build verb is the strongest thing a bullet can open with. One missing
    from the coverage list would raise an advisory on the best bullets."""
    spell = lambda phrase: " ".join(  # noqa: E731
        bundle.lexicon.spell(t) for t in phrase.lower().split()
    )
    missing = {spell(v) for v in _policy_list("build_verbs")} - {
        spell(v) for v in OPENING_VERBS
    }
    assert not missing, sorted(missing)
