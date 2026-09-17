"""G1, the technology gate."""

from __future__ import annotations

import pytest

from app.gates import check_block
from app.models import Block
from tests.conftest import bullet, codes, skills, summary
from tests.test_taxonomy_contract import HISTORICAL_FABRICATIONS

FABRICATION_SURFACES = sorted(
    {surface for forms in HISTORICAL_FABRICATIONS.values() for surface in forms}
)


def _blocks_for(surface: str) -> list[Block]:
    """The same claim in each of the three places a claim can be made."""
    return [
        bullet(f"Wrote services that used {surface} for the search path.", facts=("acme-f1",)),
        summary(f"Backend engineer with {surface} across production systems."),
        skills(f"Cloud and AI: {surface}, Python"),
    ]


@pytest.mark.parametrize("surface", FABRICATION_SURFACES)
def test_every_historical_fabrication_is_rejected_everywhere(surface, ctx):
    """Each of the six is rejected in bullet, summary, and skills text.

    Aliases, old product names, lowercase, hyphenated, and plural forms all
    included. The skills section is gated like everything else.
    """
    for block in _blocks_for(surface):
        result = check_block(block, ctx)
        assert "TECH_DENIED" in codes(result), (
            f"{surface!r} passed G1 in a {block.block_type}: {codes(result)}"
        )


def test_confirmed_technology_passes(ctx):
    result = check_block(bullet("Wrote Python services for the ingestion path."), ctx)
    assert "TECH_UNCONFIRMED" not in codes(result)
    assert "TECH_DENIED" not in codes(result)


def test_unconfirmed_technology_is_rejected(ctx):
    result = check_block(bullet("Wrote Terraform modules for the platform."), ctx)
    assert "TECH_UNCONFIRMED" in codes(result)


def test_id_absent_from_the_ledger_is_unconfirmed(ctx):
    """Absence is not permission. Redis is in the taxonomy and not in the ledger."""
    assert ctx.bundle.ledger.get("redis") is None
    result = check_block(bullet("Wrote a Redis cache layer."), ctx)
    assert "TECH_UNCONFIRMED" in codes(result)


def test_id_absent_from_the_ledger_is_not_suggestable(ctx):
    """Only an explicit unconfirmed entry may be surfaced as a gap to verify."""
    ledger = ctx.bundle.ledger
    assert ledger.is_suggestable("terraform") is True
    assert ledger.is_suggestable("redis") is False
    assert ledger.is_suggestable("java") is False


def test_denied_is_never_suggestable(ctx):
    for denied in ctx.bundle.ledger.denied_ids:
        assert ctx.bundle.ledger.is_suggestable(denied) is False


def test_jd_term_absent_from_evidence_is_rejected(ctx_with_jd):
    """The primary defence. The term need not be in the taxonomy at all."""
    ctx = ctx_with_jd("We need deep experience with Chronosphere and Bazel.")
    result = check_block(bullet("Wrote pipelines with Chronosphere for the team."), ctx)
    assert "JD_TERM_NOT_IN_EVIDENCE" in codes(result)


def test_jd_term_present_in_evidence_passes(ctx_with_jd):
    ctx = ctx_with_jd("You will write Kafka producers all day.")
    result = check_block(bullet("Wrote Kafka producers for order events.", facts=("acme-f2",)), ctx)
    assert "JD_TERM_NOT_IN_EVIDENCE" not in codes(result)


def test_synonym_permits_an_employer_term_not_literally_in_the_evidence(ctx_with_jd):
    """This is what synonyms.json is for.

    The posting says high throughput ingestion, the evidence says serverless
    ingestion platform, and an approved translation connects them.
    """
    ctx = ctx_with_jd("We want high throughput ingestion at scale.")
    result = check_block(
        bullet("Wrote the high throughput ingestion path end to end.", facts=("acme-f1",)),
        ctx,
    )
    assert "JD_TERM_NOT_IN_EVIDENCE" not in codes(result)


def test_synonym_cannot_unlock_a_denied_technology(ctx_with_jd, bundle):
    """A synonyms entry permits wording, never a technology.

    G1's taxonomy check runs independently of the corpus, so even if a posting
    term were permitted, a denied id inside it is still rejected. If this ever
    fails, synonyms.json has become a fabrication backdoor.
    """
    ctx = ctx_with_jd("Experience with Semantic Kernel required.")
    result = check_block(bullet("Wrote services on Semantic Kernel."), ctx)
    assert "TECH_DENIED" in codes(result)


def test_unknown_proper_noun_is_held_not_silently_accepted(ctx):
    result = check_block(bullet("Wrote an integration against Quibblesnort for the team."), ctx)
    assert "UNKNOWN_TERM" in codes(result)
    held = [r for r in result.rejections if r.code == "UNKNOWN_TERM"]
    assert all(r.blocks_render for r in held), "a held item must not render unapproved"


def test_ordinary_english_is_not_held(ctx):
    result = check_block(bullet("Wrote the ingestion path and documented the handover."), ctx)
    assert "UNKNOWN_TERM" not in codes(result)


def test_ambiguous_acronym_matches_as_a_whole_token(ctx):
    """SK is denied. skew, skills, and asked all contain those letters and must
    not be read as Semantic Kernel."""
    clean = check_block(bullet("Wrote code that skews results and asked for review."), ctx)
    assert "TECH_DENIED" not in codes(clean)

    hit = check_block(bullet("Wrote orchestration with SK for the agent layer."), ctx)
    assert "TECH_DENIED" in codes(hit)


def test_rejection_spans_point_at_the_offending_text(ctx):
    block = bullet("Wrote a RAG pipeline for search.")
    result = check_block(block, ctx)
    denied = [r for r in result.rejections if r.code == "TECH_DENIED"]
    assert denied
    for rejection in denied:
        assert block.text[rejection.span.start : rejection.span.end] == rejection.span.text
        assert rejection.span.text == "RAG"


def test_zero_width_characters_cannot_hide_a_denied_technology(ctx):
    """A soft hyphen or zero width space inside a name would otherwise split the
    token and slip past every gate."""
    sneaky = "Wrote a R​A­G pipeline for search."
    result = check_block(bullet(sneaky), ctx)
    assert "TECH_DENIED" in codes(result)


def test_decomposed_accents_cannot_hide_a_denied_technology(ctx):
    """Both spellings of an accented character fold to the same base letter."""
    precomposed = check_block(bullet("Wrote services on Sémantic Kernel."), ctx)
    decomposed = check_block(bullet("Wrote services on Sémantic Kernel."), ctx)
    assert "TECH_DENIED" in codes(precomposed)
    assert "TECH_DENIED" in codes(decomposed)


def test_a_posting_spelling_is_watched_in_every_form(ctx_with_jd):
    """The posting says Chronosphere Metrics; the CV says Chronosphere. The
    surface differs, the claim does not."""
    ctx = ctx_with_jd("Deep experience with Chronosphere required.")
    result = check_block(bullet("Configured Chronosphere dashboards for the team."), ctx)
    assert "JD_TERM_NOT_IN_EVIDENCE" in codes(result)
