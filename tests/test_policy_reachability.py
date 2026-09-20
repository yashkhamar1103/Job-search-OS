"""Every entry in every policy list must be reachable by its own matcher.

Three entries were found dead by reading: a two-word title modifier the
single-token matcher could never see, and two trailing hedges that only ever
appear welded onto a number, which the token-after check never looks at. Reading
found them late and by luck. Running finds them the moment they are added.

The claim here is narrow and mechanical: for each entry, construct a probe from
the entry itself, run the gate that consumes that list, and assert the expected
code fires. An entry no probe can trip is config that looks like coverage and
enforces nothing.

Each list gets probes, not one probe. Reachability is an existence claim, so an
entry that matches in any of its shapes is reachable, and "40%+" and "40ish"
being different shapes of the same trailing hedge is a fact about English rather
than a special case in the gate.
"""

from __future__ import annotations

import pytest

from app.gates import analyse, check_block
from app.normalise import token_texts
from tests.conftest import bullet, codes, skills, summary


def _attributed(rejection, entry: str) -> bool:
    """Did this finding fire because of this entry, or merely alongside it?

    The distinction matters more than it looks. "Part of the Kafka topics" is a
    weak opener and also a bullet with no verb in its first two tokens, so the
    code alone cannot say which rule spoke. Reachability asserted on the code
    alone would pass for every entry of that list, including one the matcher
    can never see, which is the failure this whole file exists to catch.

    A finding is attributed when the entry appears in the span it points at or
    in the context it carries, which is where every gate records what it
    matched.
    """
    wanted = token_texts(entry)
    if not wanted:
        # An entry that is pure punctuation, such as the tilde or the plus.
        # It has no tokens, so it can only be found as characters.
        return entry in rejection.span.text or any(
            entry in str(value) for value in rejection.context.values()
        )

    def holds(text: str) -> bool:
        have = token_texts(text)
        return any(
            have[i : i + len(wanted)] == wanted
            for i in range(0, max(0, len(have) - len(wanted) + 1))
        )

    if holds(rejection.span.text):
        return True
    return any(holds(str(value)) for value in rejection.context.values())

# ---------------------------------------------------------------------------
# Probe builders. One per list, each returning candidate blocks.
# ---------------------------------------------------------------------------


def _build_verb(entry):
    return [bullet(f"Tuned the pipeline and {entry} the Kafka topics.")]


def _weak_opener(entry):
    return [bullet(f"{entry.capitalize()} the Kafka topics for order events.")]


def _be_have(entry):
    return [bullet(f"{entry.capitalize()} the Kafka topics for order events.")]


def _banned(entry):
    return [bullet(f"Tuned the pipeline and {entry} the rollout.")]


def _intensity(entry):
    return [bullet(f"Tuned the ingestion pipeline {entry}.")]


def _quantifier(entry):
    return [bullet(f"Tuned {entry} ingestion partitions.")]


def _proficiency(entry):
    return [skills(f"Languages: Python ({entry})")]


def _duration(entry):
    return [summary(f"Engineer with {entry} of experience.")]


def _acronym(entry):
    return [bullet(f"Tuned the {entry} pipeline for order events.")]


def _leading(entry):
    return [
        bullet(f"Cut report latency by {entry} 40%.", metrics=("acme-m1",)),
        bullet(f"Cut report latency by {entry}40%.", metrics=("acme-m1",)),
    ]


def _trailing(entry):
    return [
        bullet(f"Cut report latency by 40% {entry}.", metrics=("acme-m1",)),
        bullet(f"Cut report latency by 40%{entry}.", metrics=("acme-m1",)),
        bullet(f"Cut report latency by 40{entry} percent.", metrics=("acme-m1",)),
    ]


def _unverifiable(entry):
    return [summary(f"Engineer {entry} building data platforms.")]


def _title_noun(entry):
    return [summary(f"Senior {entry.capitalize()} building data platforms.")]


def _title_modifier(entry):
    # Architect rather than Engineer: "Backend Engineer" is a title the fixture
    # world actually holds, so that probe would prove nothing.
    return [summary(f"{entry.capitalize()} Architect building data platforms.")]


#: list name -> (probe builder, the code its matcher raises)
PROBES = {
    "build_verbs": (_build_verb, "SCOPE_DEPTH"),
    "weak_openers": (_weak_opener, "WEAK_OPENING"),
    "be_have_openers": (_be_have, "WEAK_OPENING"),
    "banned_phrases": (_banned, "BANNED_VERB"),
    "vague_intensity_words": (_intensity, "VAGUE_METRIC"),
    "vague_quantifiers": (_quantifier, "UNQUANTIFIED_SCALE"),
    "proficiency_qualifiers": (_proficiency, "SKILLS_PROFICIENCY"),
    "duration_hedges": (_duration, "UNCITED_NUMBER"),
    "ambiguous_acronyms": (_acronym, "TECH_DENIED"),
    "leading_hedges": (_leading, "VAGUE_METRIC"),
    "trailing_hedges": (_trailing, "VAGUE_METRIC"),
    "unverifiable_labels": (_unverifiable, "UNVERIFIABLE_LABEL"),
    "title_nouns": (_title_noun, "TITLE_CLAIM_UNVERIFIED"),
    "title_modifiers": (_title_modifier, "TITLE_CLAIM_UNVERIFIED"),
}

#: entry -> (the code that does fire, the text that finding names).
#: Both halves are required, so an alternative route is still an assertion
#: about this entry rather than a licence to accept any finding at all.
ALTERNATIVE = {
    ("vague_quantifiers", "dozens of"): ("NUMBER_UNSUPPORTED", "dozens"),
    ("vague_quantifiers", "hundreds of"): ("NUMBER_UNSUPPORTED", "hundreds"),
    ("vague_quantifiers", "thousands of"): ("NUMBER_UNSUPPORTED", "thousands"),
}
"""These three are vague magnitude words as well as quantifiers, so they parse
as a numeric span and the number gate claims them first, naming the magnitude
word without its "of". Accepted rather than fixed: same bucket, same budget, and
the retry message is the right instruction either way. Recorded here so the next
reader does not read it as a bug."""

#: Lists checked somewhere other than a gate over a block, with where.
ELSEWHERE = {
    "opening_verbs": "coverage, asserted by absence of OPENING_VERB_UNLISTED below",
    "measurement_labels": "the claim chain, asserted on label_spans below",
    "permanently_denied_ids": "require_permanent_denials at load, asserted below",
    "client_blocklist": "ships empty by design, so it has no entries to reach",
    "location_allowlist": (
        "no consumer exists yet. Section 7's location rule is milestone 3, and "
        "until the renderer reads this list nothing can match an entry in it."
    ),
}


def _policy_lists(bundle) -> dict[str, list[str]]:
    return {
        key: value
        for key, value in bundle.policy.raw.items()
        if isinstance(value, list) and all(isinstance(v, str) for v in value)
    }


# ---------------------------------------------------------------------------
# The mechanism
# ---------------------------------------------------------------------------


def test_every_policy_list_is_either_probed_or_accounted_for(bundle):
    """A new list added to policy.json cannot arrive unprobed and unnoticed."""
    unaccounted = sorted(set(_policy_lists(bundle)) - set(PROBES) - set(ELSEWHERE))
    assert not unaccounted, (
        f"policy lists with no reachability probe: {unaccounted}. Add one to "
        f"PROBES, or an explicit reason to ELSEWHERE."
    )


def _cases():
    """(list name, entry) for every entry of every probed list.

    Collected at import time from the shipped policy, not from a fixture, so
    the suite covers the file that actually ships.
    """
    from app.loaders import ROOT, load_policy

    policy = load_policy(ROOT / "config" / "policy.json")
    return [
        (name, entry)
        for name in sorted(PROBES)
        for entry in policy.list_of(name)
    ]


@pytest.mark.parametrize("list_name,entry", _cases(), ids=lambda v: str(v))
def test_every_entry_is_reachable(list_name, entry, ctx):
    builder, expected = PROBES[list_name]
    expected, names = ALTERNATIVE.get((list_name, entry), (expected, entry))

    seen: list[list[str]] = []
    for block in builder(entry):
        result = check_block(block, ctx)
        seen.append(codes(result))
        for rejection in result.rejections:
            if rejection.code == expected and _attributed(rejection, names):
                return
    pytest.fail(
        f"{list_name} entry {entry!r} is unreachable: no probe raised {expected} "
        f"naming it. Probes returned {seen}. Either the entry can never match, "
        f"or its matcher does not read the shape it is written in."
    )


# ---------------------------------------------------------------------------
# The lists whose matcher is not a rejection over a block
# ---------------------------------------------------------------------------


def test_every_opening_verb_is_reachable_as_coverage(bundle, ctx):
    """An opening verb is consumed by its absence: a bullet opening with it
    must raise no advisory. One that also trips the denylist would never reach
    the coverage check, so the denylist is asserted quiet too."""
    unreachable = []
    for verb in bundle.policy.list_of("opening_verbs"):
        found = codes(check_block(bullet(f"{verb.capitalize()} the ingestion path."), ctx))
        if "OPENING_VERB_UNLISTED" in found or "WEAK_OPENING" in found:
            unreachable.append((verb, found))
    assert not unreachable, unreachable


def test_a_one_word_trailing_hedge_is_reachable_welded_as_well_as_spaced(bundle, ctx):
    """Reachability is an existence claim, and that is its weakness.

    "40% ish" is an input that matches, so the probe above passes on it, and
    "ish" was reachable in that sense while being dead in the only shape anyone
    writes it. Any single alphabetic hedge can be welded onto the number, so
    both shapes are asserted rather than either.
    """
    dead = []
    for hedge in bundle.policy.list_of("trailing_hedges"):
        if not hedge.isalpha():
            continue
        welded = codes(check_block(bullet(f"Cut report latency by 40{hedge} percent."), ctx))
        spaced = codes(check_block(bullet(f"Cut report latency by 40% {hedge}."), ctx))
        if "VAGUE_METRIC" not in welded or "VAGUE_METRIC" not in spaced:
            dead.append((hedge, {"welded": welded, "spaced": spaced}))
    assert not dead, dead


def test_every_measurement_label_is_reachable(bundle, ctx):
    """The label list is consumed by the claim chain rather than by a gate, so
    reachability is a span, not a code."""
    unreachable = []
    for label in bundle.policy.list_of("measurement_labels"):
        block = bullet(f"Tuned the reporting queries to hold {label} steady.")
        if not analyse(block, ctx).label_spans:
            unreachable.append(label)
    assert not unreachable, unreachable


def test_every_permanently_denied_id_is_reachable(bundle):
    """Consumed at load rather than by a gate. An id the check never names is
    an id nothing protects."""
    from app.loaders import EvidenceError, Ledger, Policy, require_permanent_denials

    for canonical_id in bundle.policy.list_of("permanently_denied_ids"):
        policy = Policy({"permanently_denied_ids": [canonical_id]}, None)
        with pytest.raises(EvidenceError, match=canonical_id):
            require_permanent_denials(Ledger({}), policy)
