"""G3, the number gate."""

from __future__ import annotations

import pytest

from app.gates import check_block
from app.numbers import extract, supported_keys
from tests.conftest import assert_rejects, bullet, codes, skills, summary


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


def test_bullet_with_no_fact_citation_is_rejected(ctx):
    result = assert_rejects(bullet("Configured the ingestion path.", facts=()), ctx, "CITATION_MISSING")
    assert "CITATION_MISSING" in codes(result)


def test_unknown_fact_id_is_rejected(ctx):
    result = assert_rejects(bullet("Configured the ingestion path.", facts=("nope-f9",)), ctx, "CITATION_UNKNOWN")
    assert "CITATION_UNKNOWN" in codes(result)


def test_unknown_metric_id_is_rejected(ctx):
    result = assert_rejects(
        bullet("Configured the ingestion path.", facts=("acme-f1",), metrics=("nope-m9",)), ctx, "CITATION_UNKNOWN"
    )
    assert "CITATION_UNKNOWN" in codes(result)


# ---------------------------------------------------------------------------
# Numbers in bullets
# ---------------------------------------------------------------------------


def test_number_matching_a_cited_metric_passes(ctx):
    result = check_block(
        bullet("Reduced ingestion latency by 40%.", metrics=("acme-m1",)), ctx
    )
    assert "NUMBER_UNSUPPORTED" not in codes(result)


def test_number_not_in_the_cited_metrics_is_rejected(ctx):
    result = assert_rejects(
        bullet("Reduced ingestion latency by 55%.", metrics=("acme-m1",)), ctx, "NUMBER_UNSUPPORTED"
    )
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_number_with_no_metric_cited_at_all_is_rejected(ctx):
    result = assert_rejects(bullet("Reduced ingestion latency by 40%."), ctx, "NUMBER_UNSUPPORTED")
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_a_metric_cited_by_another_bullet_does_not_support_this_one(ctx):
    """Citations are per bullet. bolt-m1 is 3x and is not cited here."""
    result = assert_rejects(
        bullet("Reduced ingestion latency by 3x.", metrics=("acme-m1",)), ctx, "NUMBER_UNSUPPORTED"
    )
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_kind_is_part_of_the_claim(ctx):
    """40 and 40% are different claims. A metric of 40% does not support 40.

    Reported as NUMBER_FORM_MISMATCH rather than NUMBER_UNSUPPORTED: the value
    is in the cited metrics, the form is not, and a retry told which form to use
    converges instead of guessing at a number it already has.
    """
    result = assert_rejects(
        bullet("Configured 40 ingestion partitions.", metrics=("acme-m1",)), ctx, "NUMBER_FORM_MISMATCH"
    )
    assert "NUMBER_FORM_MISMATCH" in codes(result)
    assert "NUMBER_UNSUPPORTED" not in codes(result)


def test_an_invented_number_is_unsupported_not_a_form_mismatch(ctx):
    """The split has to cut both ways or it is just a rename."""
    result = assert_rejects(
        bullet("Reduced ingestion latency by 55%.", metrics=("acme-m1",)), ctx, "NUMBER_UNSUPPORTED"
    )
    assert "NUMBER_UNSUPPORTED" in codes(result)
    assert "NUMBER_FORM_MISMATCH" not in codes(result)


def test_magnitude_and_long_form_are_the_same_number(ctx):
    """acme-m2 records 2.5M records. Writing it out must still pass."""
    scaled = check_block(
        bullet("Ingested 2.5M records each day.", metrics=("acme-m2",)), ctx
    )
    written = check_block(
        bullet("Ingested 2,500,000 records each day.", metrics=("acme-m2",)), ctx
    )
    assert "NUMBER_UNSUPPORTED" not in codes(scaled)
    assert "NUMBER_UNSUPPORTED" not in codes(written)


def test_a_plus_is_a_different_claim_from_the_bare_number(ctx):
    """A metric of 40% does not support a claim of 40% or more.

    Now a trailing hedge: the plus widens a number the metric records exactly.
    """
    result = assert_rejects(
        bullet("Reduced ingestion latency by 40%+.", metrics=("acme-m1",)), ctx, "VAGUE_METRIC"
    )
    assert "VAGUE_METRIC" in codes(result)


@pytest.mark.parametrize(
    "text",
    [
        "Reduced ingestion latency by roughly 40%.",
        "Reduced ingestion latency by about 40%.",
        "Reduced ingestion latency by up to 40%.",
        "Reduced ingestion latency by 40% or more.",
        "Reduced ingestion latency by 40% or so.",
    ],
)
def test_a_hedge_attached_to_a_number_is_rejected(text, ctx):
    result = assert_rejects(bullet(text, metrics=("acme-m1",)), ctx, "VAGUE_METRIC")
    assert "VAGUE_METRIC" in codes(result)


@pytest.mark.parametrize(
    "text",
    [
        "Reduced ingestion latency by 40% over the prior release.",
        "Configured the ingestion path over the weekend window.",
    ],
)
def test_a_hedge_word_after_the_number_or_with_no_number_is_not_a_hedge(text, ctx):
    """Position is the whole rule. The same word compares, hedges, or is just a
    preposition, depending on where it sits."""
    result = check_block(bullet(text, metrics=("acme-m1",)), ctx)
    assert "VAGUE_METRIC" not in codes(result)


def test_a_plus_inside_a_language_name_is_not_a_trailing_hedge(ctx):
    """F1. C++ carries two plus signs and neither widens anything.

    The bullet also carries a real number, so the hedge check is reached rather
    than skipped for want of anything to hedge.
    """
    result = check_block(
        bullet("Configured 40% of the C++ build pipeline.", metrics=("acme-m1",)), ctx
    )
    assert "VAGUE_METRIC" not in codes(result)


def test_a_plus_attached_to_a_number_is_still_a_trailing_hedge(ctx):
    """F2. The paired positive, so F1 cannot be satisfied by switching the
    rule off."""
    result = assert_rejects(bullet("Configured 12+ ingestion partitions."), ctx, "VAGUE_METRIC")
    assert "VAGUE_METRIC" in codes(result)


# ---------------------------------------------------------------------------
# Bounds are measurements
# ---------------------------------------------------------------------------


def test_a_hedge_a_cited_metric_records_verbatim_is_legal(ctx):
    """acme-m3 is recorded as "under 200ms". A latency bound is a measured
    value whose form contains the word under, and rewriting it as 200ms would
    claim something the measurement does not support."""
    result = check_block(
        bullet("Tuned the reporting queries to hold read latency under 200ms.", metrics=("acme-m3",)), ctx
    )
    assert "VAGUE_METRIC" not in codes(result)


def test_the_same_hedge_with_a_different_number_is_still_rejected(ctx):
    """The exemption is the metric's exact text, not the word under."""
    result = assert_rejects(
        bullet("Tuned the reporting queries to hold read latency under 250ms.", metrics=("acme-m3",)),
        ctx,
        "VAGUE_METRIC",
    )
    assert "VAGUE_METRIC" in codes(result)


def test_the_hedge_exemption_needs_the_metric_to_be_cited(ctx):
    """Legal where the metric says it, illegal everywhere else."""
    result = assert_rejects(
        bullet("Tuned the reporting queries to hold read latency under 200ms.", metrics=("acme-m1",)),
        ctx,
        "VAGUE_METRIC",
    )
    assert "VAGUE_METRIC" in codes(result)


def test_a_different_hedge_on_the_same_metric_is_still_rejected(ctx):
    """"roughly 200ms" is not what the metric records, so it widens it."""
    result = assert_rejects(
        bullet("Tuned the reporting queries to roughly 200ms.", metrics=("acme-m3",)),
        ctx,
        "VAGUE_METRIC",
    )
    assert "VAGUE_METRIC" in codes(result)


def test_a_percentile_label_is_currently_read_as_a_number(ctx):
    """Characterisation, not endorsement. Open question for Yash.

    p95 and p99 are labels for which measurement was taken, not claims about
    scale, but the digits inside them parse as a number like any other and the
    only exemption the spec grants is for digits inside a matched taxonomy
    alias. So a truthful latency bullet is rejected today, and the remedy is a
    spec decision about identifier-internal digits, not a quiet edit here.
    """
    result = assert_rejects(
        bullet("Tuned the reporting queries to hold p95 under 200ms.", metrics=("acme-m3",)),
        ctx,
        "NUMBER_UNSUPPORTED",
    )
    assert "NUMBER_UNSUPPORTED" in codes(result)
    assert [r.span.text for r in result.rejections if r.code == "NUMBER_UNSUPPORTED"] == ["95"]


def test_the_exemption_does_not_reach_a_block_with_no_citations(ctx):
    """A summary cites nothing, so no metric can make a bound legal there."""
    result = assert_rejects(summary("Backend engineer holding read latency under 200ms."), ctx, "UNCITED_NUMBER")
    assert "UNCITED_NUMBER" in codes(result)


# ---------------------------------------------------------------------------
# Unquantified scale
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Configured numerous ingestion partitions for order events.",
        "Configured several ingestion partitions for order events.",
        "Configured a handful of ingestion partitions for order events.",
    ],
)
def test_a_quantifier_with_no_number_in_the_clause_is_rejected(text, ctx):
    result = assert_rejects(bullet(text), ctx, "UNQUANTIFIED_SCALE")
    assert "UNQUANTIFIED_SCALE" in codes(result)


def test_a_number_in_the_same_clause_excuses_the_quantifier(ctx):
    """The claim then carries its own quantity, which G3 checks as a number."""
    result = check_block(
        bullet("Configured 40% of the several ingestion partitions.", metrics=("acme-m1",)), ctx
    )
    assert "UNQUANTIFIED_SCALE" not in codes(result)


def test_a_number_in_a_different_clause_does_not_excuse_it(ctx):
    """A number about something else is not the missing count."""
    result = assert_rejects(
        bullet("Cut latency by 40%, then tuned several ingestion partitions.", metrics=("acme-m1",)),
        ctx,
        "UNQUANTIFIED_SCALE",
    )
    assert "UNQUANTIFIED_SCALE" in codes(result)


def test_a_quantifier_over_a_mass_noun_does_not_fire(ctx):
    """"various tooling" asserts no count, so there is no count to be missing."""
    result = check_block(bullet("Configured various tooling for order events."), ctx)
    assert "UNQUANTIFIED_SCALE" not in codes(result)


def test_a_plural_noun_with_no_quantifier_does_not_fire(ctx):
    result = check_block(bullet("Configured the ingestion partitions for order events."), ctx)
    assert "UNQUANTIFIED_SCALE" not in codes(result)


def test_a_vague_magnitude_word_is_read_as_a_number_not_a_quantifier(ctx):
    """"thousands of" is both a quantifier and a vague magnitude word. Gate
    precedence gives the span to the number gate, which rejects it as
    unsupported, so the claim is caught once rather than named twice."""
    result = assert_rejects(bullet("Ingested thousands of records each day."), ctx, "NUMBER_UNSUPPORTED")
    assert "NUMBER_UNSUPPORTED" in codes(result)
    assert "UNQUANTIFIED_SCALE" not in codes(result)


def test_a_quantifier_in_the_summary_is_rejected_too(ctx):
    """The summary carries no citations at all, so a quantifier there has even
    less to stand on than one in a bullet."""
    result = assert_rejects(
        summary("Backend engineer who built numerous data platforms."), ctx, "UNQUANTIFIED_SCALE"
    )
    assert "UNQUANTIFIED_SCALE" in codes(result)


def test_number_words_are_extracted(ctx):
    result = assert_rejects(bullet("Configured three ingestion partitions."), ctx, "NUMBER_UNSUPPORTED")
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_vague_magnitude_words_are_extracted(ctx):
    result = assert_rejects(bullet("Ingested thousands of records each day."), ctx, "NUMBER_UNSUPPORTED")
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_bullet_with_no_numbers_passes(ctx):
    result = check_block(bullet("Configured the ingestion path for order events."), ctx)
    assert "NUMBER_UNSUPPORTED" not in codes(result)


# ---------------------------------------------------------------------------
# Vague intensity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["significantly", "dramatically", "substantially", "massively"])
def test_vague_intensity_words_are_rejected(word, ctx):
    result = assert_rejects(bullet(f"Reduced ingestion latency {word}."), ctx, "VAGUE_METRIC")
    assert "VAGUE_METRIC" in codes(result)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


def test_listed_version_passes(ctx):
    """dotnet is confirmed under bolt with versions ["8"]."""
    result = check_block(
        bullet("Wrote .NET 8 services for reporting.", role="bolt", facts=("bolt-f1",)), ctx
    )
    assert "VERSION_UNSUPPORTED" not in codes(result)


def test_unlisted_version_is_rejected(ctx):
    result = assert_rejects(
        bullet("Wrote .NET 6 services for reporting.", role="bolt", facts=("bolt-f1",)), ctx, "VERSION_UNSUPPORTED"
    )
    assert "VERSION_UNSUPPORTED" in codes(result)


def test_a_version_is_not_checked_against_metrics(ctx):
    """A version is not a claim about scale, so it must not also raise
    NUMBER_UNSUPPORTED."""
    result = check_block(
        bullet("Wrote .NET 8 services for reporting.", role="bolt", facts=("bolt-f1",)), ctx
    )
    assert "NUMBER_UNSUPPORTED" not in codes(result)


def test_digits_inside_a_product_name_are_not_numbers(ctx):
    """Route 53 and OAuth 2.0 carry digits that belong to the name."""
    result = check_block(bullet("Configured Amazon Route 53 records for the platform."), ctx)
    assert "NUMBER_UNSUPPORTED" not in codes(result)
    assert "VERSION_UNSUPPORTED" not in codes(result)


# ---------------------------------------------------------------------------
# Summary and skills: no citations exist, so no numbers
# ---------------------------------------------------------------------------


def test_uncited_number_in_the_summary_is_rejected(ctx):
    result = assert_rejects(summary("Backend engineer who cut latency by 40%."), ctx, "UNCITED_NUMBER")
    assert "UNCITED_NUMBER" in codes(result)


def test_a_real_metric_does_not_rescue_a_summary_number(ctx):
    """acme-m1 really is 40%. The summary still cannot carry it: there is no
    citation on a summary, so nothing ties the number to the claim."""
    result = assert_rejects(summary("Cut ingestion latency by 40% at a previous employer."), ctx, "UNCITED_NUMBER")
    assert "UNCITED_NUMBER" in codes(result)


def test_computed_total_years_is_permitted_in_the_summary(ctx):
    """The one exception: a value this codebase derived from the role dates."""
    years = ctx.computed.total_years
    result = check_block(summary(f"Backend engineer with {years} years building data platforms."), ctx)
    assert "UNCITED_NUMBER" not in codes(result)


def test_computed_total_years_plus_form_is_permitted(ctx):
    years = ctx.computed.total_years
    result = check_block(summary(f"Backend engineer with {years}+ years of experience."), ctx)
    assert "UNCITED_NUMBER" not in codes(result)


def test_a_wrong_years_figure_is_rejected(ctx):
    years = ctx.computed.total_years
    result = assert_rejects(summary(f"Backend engineer with {years + 2} years of experience."), ctx, "UNCITED_NUMBER")
    assert "UNCITED_NUMBER" in codes(result)


@pytest.mark.parametrize("hedge", ["nearly", "almost", "over", "more than"])
def test_duration_hedges_are_rejected_in_the_summary(hedge, ctx):
    years = ctx.computed.total_years
    result = assert_rejects(summary(f"Backend engineer with {hedge} {years} years of experience."), ctx, "UNCITED_NUMBER")
    assert "UNCITED_NUMBER" in codes(result)


@pytest.mark.parametrize("phrase", ["half a decade", "a decade"])
def test_decade_phrasings_are_rejected_in_the_summary(phrase, ctx):
    result = assert_rejects(summary(f"Backend engineer with {phrase} of experience."), ctx, "UNCITED_NUMBER")
    assert "UNCITED_NUMBER" in codes(result)


def test_vague_intensity_in_the_summary_uses_the_summary_code(ctx):
    result = assert_rejects(summary("Backend engineer who significantly improved throughput."), ctx, "UNCITED_NUMBER")
    assert "UNCITED_NUMBER" in codes(result)
    assert "VAGUE_METRIC" not in codes(result)


def test_numbers_in_the_skills_section_are_rejected(ctx):
    result = assert_rejects(skills("Languages: Python, 5 years"), ctx, "UNCITED_NUMBER")
    assert "UNCITED_NUMBER" in codes(result)


# ---------------------------------------------------------------------------
# The extractor itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,kind",
    [
        ("40%", "percent"),
        ("3x", "multiplier"),
        ("$1.2M", "currency"),
        ("3-5", "range"),
        ("50+", "plain"),
        ("10K", "plain"),
        ("2,500,000", "plain"),
        ("7", "plain"),
    ],
)
def test_extractor_kinds(text, kind):
    found = extract(text)
    assert found, f"nothing extracted from {text!r}"
    assert found[0].canonical.kind == kind


def test_scaled_and_written_numbers_share_a_key():
    assert supported_keys(["2.5M"]) == supported_keys(["2,500,000"])
