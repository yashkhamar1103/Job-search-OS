"""G3, the number gate."""

from __future__ import annotations

import pytest

from app.gates import check_block
from app.numbers import extract, supported_keys
from tests.conftest import bullet, codes, skills, summary


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


def test_bullet_with_no_fact_citation_is_rejected(ctx):
    result = check_block(bullet("Configured the ingestion path.", facts=()), ctx)
    assert "CITATION_MISSING" in codes(result)


def test_unknown_fact_id_is_rejected(ctx):
    result = check_block(bullet("Configured the ingestion path.", facts=("nope-f9",)), ctx)
    assert "CITATION_UNKNOWN" in codes(result)


def test_unknown_metric_id_is_rejected(ctx):
    result = check_block(
        bullet("Configured the ingestion path.", facts=("acme-f1",), metrics=("nope-m9",)), ctx
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
    result = check_block(
        bullet("Reduced ingestion latency by 55%.", metrics=("acme-m1",)), ctx
    )
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_number_with_no_metric_cited_at_all_is_rejected(ctx):
    result = check_block(bullet("Reduced ingestion latency by 40%."), ctx)
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_a_metric_cited_by_another_bullet_does_not_support_this_one(ctx):
    """Citations are per bullet. bolt-m1 is 3x and is not cited here."""
    result = check_block(
        bullet("Reduced ingestion latency by 3x.", metrics=("acme-m1",)), ctx
    )
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_kind_is_part_of_the_claim(ctx):
    """40 and 40% are different claims. A metric of 40% does not support 40."""
    result = check_block(
        bullet("Configured 40 ingestion partitions.", metrics=("acme-m1",)), ctx
    )
    assert "NUMBER_UNSUPPORTED" in codes(result)


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
    """A metric of 40% does not support a claim of 40% or more."""
    result = check_block(
        bullet("Reduced ingestion latency by 40%+.", metrics=("acme-m1",)), ctx
    )
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_number_words_are_extracted(ctx):
    result = check_block(bullet("Configured three ingestion partitions."), ctx)
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_vague_magnitude_words_are_extracted(ctx):
    result = check_block(bullet("Ingested thousands of records each day."), ctx)
    assert "NUMBER_UNSUPPORTED" in codes(result)


def test_bullet_with_no_numbers_passes(ctx):
    result = check_block(bullet("Configured the ingestion path for order events."), ctx)
    assert "NUMBER_UNSUPPORTED" not in codes(result)


# ---------------------------------------------------------------------------
# Vague intensity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["significantly", "dramatically", "substantially", "massively"])
def test_vague_intensity_words_are_rejected(word, ctx):
    result = check_block(bullet(f"Reduced ingestion latency {word}."), ctx)
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
    result = check_block(
        bullet("Wrote .NET 6 services for reporting.", role="bolt", facts=("bolt-f1",)), ctx
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
    result = check_block(summary("Backend engineer who cut latency by 40%."), ctx)
    assert "UNCITED_NUMBER" in codes(result)


def test_a_real_metric_does_not_rescue_a_summary_number(ctx):
    """acme-m1 really is 40%. The summary still cannot carry it: there is no
    citation on a summary, so nothing ties the number to the claim."""
    result = check_block(summary("Cut ingestion latency by 40% at a previous employer."), ctx)
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
    result = check_block(summary(f"Backend engineer with {years + 2} years of experience."), ctx)
    assert "UNCITED_NUMBER" in codes(result)


@pytest.mark.parametrize("hedge", ["nearly", "almost", "over", "more than"])
def test_duration_hedges_are_rejected_in_the_summary(hedge, ctx):
    years = ctx.computed.total_years
    result = check_block(summary(f"Backend engineer with {hedge} {years} years of experience."), ctx)
    assert "UNCITED_NUMBER" in codes(result)


@pytest.mark.parametrize("phrase", ["half a decade", "a decade"])
def test_decade_phrasings_are_rejected_in_the_summary(phrase, ctx):
    result = check_block(summary(f"Backend engineer with {phrase} of experience."), ctx)
    assert "UNCITED_NUMBER" in codes(result)


def test_vague_intensity_in_the_summary_uses_the_summary_code(ctx):
    result = check_block(summary("Backend engineer who significantly improved throughput."), ctx)
    assert "UNCITED_NUMBER" in codes(result)
    assert "VAGUE_METRIC" not in codes(result)


def test_numbers_in_the_skills_section_are_rejected(ctx):
    result = check_block(skills("Languages: Python, 5 years"), ctx)
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
