"""The bucket table is the contract, and this is what holds it to it.

app/gates/buckets.py pins every code to a bucket, a severity and a retry
budget. These tests assert the table and the registry in app.errors agree in
both directions, so a code cannot change bucket, be added, or be removed
without the table being edited on purpose.

The point is narrow and worth stating: a truth gate must not become an advisory
as a side effect of a refactor. Downgrading one is a decision, and a decision
should require a diff somebody reads.
"""

from __future__ import annotations

import pytest

from app.errors import CODES, Bucket, Severity
from app.gates import buckets

_BUCKETS = {"truth": Bucket.TRUTH, "style": Bucket.STYLE, "structure": Bucket.STRUCTURE}
_SEVERITIES = {"reject": Severity.REJECT, "hold": Severity.HOLD, "advisory": Severity.ADVISORY}


def test_the_table_and_the_registry_cover_the_same_codes():
    missing_from_table = sorted(set(CODES) - set(buckets.TABLE))
    missing_from_registry = sorted(set(buckets.TABLE) - set(CODES))
    assert not missing_from_table, (
        f"codes exist with no entry in the bucket table: {missing_from_table}. "
        f"Add them to app/gates/buckets.py deliberately."
    )
    assert not missing_from_registry, (
        f"the bucket table names codes that do not exist: {missing_from_registry}"
    )


@pytest.mark.parametrize("code", sorted(buckets.TABLE))
def test_each_code_matches_its_pinned_bucket_and_severity(code):
    bucket, severity, _retries = buckets.TABLE[code]
    spec = CODES[code]
    assert spec.bucket is _BUCKETS[bucket], (
        f"{code} is registered as {spec.bucket.value} but the table pins {bucket}"
    )
    assert spec.severity is _SEVERITIES[severity], (
        f"{code} is registered as {spec.severity.value} but the table pins {severity}"
    )


@pytest.mark.parametrize("code", sorted(buckets.TABLE))
def test_each_code_matches_its_pinned_retry_budget(code):
    _bucket, _severity, retries = buckets.TABLE[code]
    assert CODES[code].retries == retries, (
        f"{code} overrides retries as {CODES[code].retries}, table pins {retries}"
    )


def test_the_hygiene_gate_gets_no_retries():
    """A homoglyph is not a phrasing problem a regeneration fixes."""
    for code in ("INVISIBLE_CHAR", "MIXED_SCRIPT", "NON_LATIN_SCRIPT"):
        assert buckets.TABLE[code] == ("truth", "reject", 0)


def test_only_the_intended_codes_are_advisory():
    """An advisory never blocks. The list of them is short and deliberate."""
    assert buckets.ADVISORY_ONLY == {"OPENING_VERB_UNLISTED", "TITLE_CLAIM_UNVERIFIED"}


def test_no_advisory_code_blocks_rendering():
    for code in buckets.ADVISORY_ONLY:
        assert CODES[code].severity is Severity.ADVISORY
        assert CODES[code].exhaustion.value == "render_and_flag"


def test_every_truth_code_drops_or_holds_rather_than_rendering():
    """A truth finding must never end up rendered and merely flagged."""
    for code in buckets.TRUTH_CODES:
        assert CODES[code].exhaustion.value in ("drop", "hold_for_review"), code


def test_retries_for_uses_the_override_then_the_bucket():
    limits = {"truth": 2, "style": 1, "structure": 0}
    assert buckets.retries_for("TECH_DENIED", limits) == 2
    assert buckets.retries_for("TOO_LONG", limits) == 1
    assert buckets.retries_for("MIXED_SCRIPT", limits) == 0
    assert buckets.retries_for("UNVERIFIABLE_LABEL", limits) == 1
