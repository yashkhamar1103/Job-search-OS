"""Paired positives and negatives for gates that had only one side.

A gate with a "fires" test and no "does not fire" test is half specified. The
firing test says the gate is capable of rejecting; nothing says it is capable of
staying quiet, and a gate that rejected everything would pass it. That is the
failure mode that gets gates switched off by the person using them.

Each pair here is one code: an input that should trip it, and a neighbouring
input that should not. The positive side runs through `assert_rejects`, so the
rule's input is asserted present before the verdict is read.
"""

from __future__ import annotations

import pytest

from app.errors import CODES
from tests.conftest import (
    assert_does_not_reject,
    assert_rejects,
    bullet,
    context_for,
    skills,
    summary,
    with_policy,
)
from tests.preconditions import DOCUMENT_CODES, PRECONDITIONS


# ---------------------------------------------------------------------------
# The mechanism itself
# ---------------------------------------------------------------------------


def test_every_registered_code_has_a_precondition():
    """A new code without one would let its first test go green asserting nothing.

    G5's codes are exempt until milestone 3 gives them a block to fire on, and
    SCHEMA_INVALID belongs to model output rather than to any block.
    """
    exempt = {
        "ROUNDTRIP_TEXT_MISSING",
        "ROUNDTRIP_ORDER",
        "ROUNDTRIP_STRUCTURE",
        "PAGE_COUNT_EXCEEDED",
        "SCHEMA_INVALID",
    }
    missing = sorted(set(CODES) - set(PRECONDITIONS) - DOCUMENT_CODES - exempt)
    assert not missing, (
        f"codes with no precondition: {missing}. Add one to tests/preconditions.py "
        f"or a test of it can pass while its input contains nothing."
    )


def test_a_precondition_that_stops_holding_raises(ctx):
    """The mechanism must fail loudly, not quietly.

    This is finding 2 reconstructed. "Kafka streams" reads as the product Kafka
    Streams, so the sentence holds one confirmed technology, and a cohabitation
    test written against it asserts nothing.
    """
    from tests.preconditions import PreconditionError

    hollow = bullet("Connected Kafka streams into PostgreSQL for reporting.", role="acme")
    with pytest.raises(PreconditionError, match="two confirmed technologies"):
        assert_rejects(hollow, ctx, "SCOPE_COHABITATION")

    intact = bullet("Connected Kafka topics into PostgreSQL for reporting.", role="acme")
    assert_rejects(intact, ctx, "SCOPE_COHABITATION")


# ---------------------------------------------------------------------------
# The ten pairs
# ---------------------------------------------------------------------------


def test_banned_verb_pair(ctx):
    assert_rejects(bullet("Configured the path and spearheaded the rollout."), ctx, "BANNED_VERB")
    assert_does_not_reject(bullet("Configured the path and led the rollout."), ctx, "BANNED_VERB")


def test_banned_verb_does_not_fire_on_a_word_that_merely_starts_the_same(ctx):
    """"delivered on" is banned; "delivered" alone is a real claim."""
    assert_does_not_reject(bullet("Delivered the ingestion path for order events."), ctx, "BANNED_VERB")


def test_citation_missing_pair(ctx):
    assert_rejects(bullet("Configured the ingestion path.", facts=()), ctx, "CITATION_MISSING")
    assert_does_not_reject(bullet("Configured the ingestion path."), ctx, "CITATION_MISSING")


def test_citation_missing_does_not_fire_outside_a_bullet(ctx):
    """The summary carries no citations, so it cannot be missing one."""
    assert_does_not_reject(summary("Backend engineer building data platforms."), ctx, "CITATION_MISSING")


def test_citation_unknown_pair(ctx):
    assert_rejects(bullet("Configured the path.", facts=("nope-f9",)), ctx, "CITATION_UNKNOWN")
    assert_does_not_reject(bullet("Configured the path.", facts=("acme-f1",)), ctx, "CITATION_UNKNOWN")


def test_em_dash_pair(ctx):
    from app.gates.g4_structure import EM_DASH

    assert_rejects(bullet(f"Configured the path {EM_DASH} for order events."), ctx, "EM_DASH")
    assert_does_not_reject(bullet("Configured the path, then handled order events."), ctx, "EM_DASH")


def test_a_single_hyphen_is_not_a_dash(ctx):
    """Only the em dash, the horizontal bar and the double hyphen are banned."""
    assert_does_not_reject(bullet("Configured the well-known ingestion path."), ctx, "EM_DASH")


def test_skills_proficiency_pair(ctx):
    assert_rejects(skills("Languages: Python (Expert)"), ctx, "SKILLS_PROFICIENCY")
    assert_does_not_reject(skills("Languages: Python"), ctx, "SKILLS_PROFICIENCY")


def test_skills_proficiency_does_not_fire_outside_the_skills_section(ctx):
    """A bullet may legitimately contain the word advanced."""
    assert_does_not_reject(
        bullet("Configured the advanced retry path for order events."), ctx, "SKILLS_PROFICIENCY"
    )


def test_invisible_char_pair(ctx):
    assert_rejects(bullet("Configured the Kafka​ topics."), ctx, "INVISIBLE_CHAR")
    assert_does_not_reject(bullet("Configured the Kafka topics."), ctx, "INVISIBLE_CHAR")


def test_ordinary_whitespace_is_not_an_invisible_character(ctx):
    assert_does_not_reject(bullet("Configured  the\tKafka topics."), ctx, "INVISIBLE_CHAR")


def test_mixed_script_pair(ctx):
    assert_rejects(bullet("Configured the Kafkа topics."), ctx, "MIXED_SCRIPT")
    assert_does_not_reject(bullet("Configured the Kafka topics."), ctx, "MIXED_SCRIPT")


def test_non_latin_script_pair(ctx):
    assert_rejects(bullet("Configured the Kafkа topics."), ctx, "NON_LATIN_SCRIPT")
    assert_does_not_reject(bullet("Configured the Kafka topics."), ctx, "NON_LATIN_SCRIPT")


@pytest.mark.parametrize("text", ["naïve", "résumé", "Zürich", "café"])
def test_latin_extended_accents_stay_legal(text, ctx):
    """Rejecting an accent would be a bug, not a defence."""
    block = bullet(f"Configured the {text} retry path for order events.")
    assert_does_not_reject(block, ctx, "NON_LATIN_SCRIPT", "MIXED_SCRIPT")


def test_unverifiable_label_pair(ctx):
    assert_rejects(summary("Seasoned engineer across data platforms."), ctx, "UNVERIFIABLE_LABEL")
    assert_does_not_reject(summary("Engineer across data platforms."), ctx, "UNVERIFIABLE_LABEL")


def test_unverifiable_label_does_not_fire_in_the_skills_section(ctx):
    """Checked in the summary and in bullets, which is where prose lives."""
    assert_does_not_reject(skills("Approach: seasoned"), ctx, "UNVERIFIABLE_LABEL")


def test_title_claim_pair(ctx):
    assert_rejects(
        summary("Senior Solutions Architect working across data platforms."),
        ctx,
        "TITLE_CLAIM_UNVERIFIED",
    )
    assert_does_not_reject(
        summary("Backend Engineer working across data platforms."), ctx, "TITLE_CLAIM_UNVERIFIED"
    )


def test_a_single_capitalised_word_is_not_a_title_claim(ctx):
    """A summary opening with Engineer capitalised its first word because it is
    the first word. Reading that as a title claim would flag every summary."""
    assert_does_not_reject(
        summary("Engineer building data platforms for reporting."), ctx, "TITLE_CLAIM_UNVERIFIED"
    )


def test_client_name_pair(bundle):
    blocked = context_for(with_policy(bundle, client_blocklist=["Northwind Traders"]))
    assert_rejects(bullet("Configured the path for Northwind Traders."), blocked, "CLIENT_NAME")
    assert_does_not_reject(
        bullet("Configured the path for the retail team."), blocked, "CLIENT_NAME"
    )


def test_client_name_reports_one_name_once(bundle):
    """Longest match wins, so an entry contained in another does not double up."""
    blocked = context_for(
        with_policy(bundle, client_blocklist=["Northwind Traders", "Northwind"])
    )
    result = assert_rejects(
        bullet("Configured the path for Northwind Traders."), blocked, "CLIENT_NAME"
    )
    hits = [r for r in result.rejections if r.code == "CLIENT_NAME"]
    assert len(hits) == 1, [str(r) for r in hits]
    assert hits[0].span.text == "Northwind Traders"
