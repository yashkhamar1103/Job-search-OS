"""Shared test fixtures.

The fixture world is loaded against the REAL vocab/taxonomy.json and the REAL
config/policy.json. Only the evidence files are fictional. A gate test that ran
against a convenient toy taxonomy would prove the gate works on a taxonomy
nobody ships.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.computed import total_years_experience
from app.gates.context import GateContext
from app.jd import WatchList, build_watch_list
from app.loaders import ROOT, load_bundle
from app.models import Block, Document

FIXTURES = Path(__file__).parent / "fixtures"

#: Every run anchored to one date, so a test asserting a years figure does not
#: start failing on a birthday.
ANCHOR = date(2026, 3, 31)


@pytest.fixture(scope="session")
def bundle():
    return load_bundle(ROOT, evidence_dir=FIXTURES)


@pytest.fixture(scope="session")
def real_bundle_paths():
    return {
        "taxonomy": ROOT / "vocab" / "taxonomy.json",
        "confusables": ROOT / "vocab" / "confusables.json",
        "ledger": ROOT / "evidence" / "ledger.json",
    }


@pytest.fixture
def ctx(bundle) -> GateContext:
    return GateContext(
        bundle=bundle,
        watch=WatchList(),
        computed=total_years_experience(bundle.experience, anchor=ANCHOR),
        run_date=ANCHOR,
    )


@pytest.fixture
def ctx_with_jd(bundle):
    def build(jd_text: str) -> GateContext:
        watch, _ = build_watch_list(jd_text, bundle)
        return GateContext(
            bundle=bundle,
            watch=watch,
            computed=total_years_experience(bundle.experience, anchor=ANCHOR),
            run_date=ANCHOR,
        )

    return build


def with_policy(bundle, **overrides):
    """A copy of the bundle with policy values replaced.

    A copy rather than a mutation: the bundle fixture is session scoped, and a
    test that edited it in place would change what every later test is checking.
    """
    import dataclasses

    from app.loaders import Policy

    raw = dict(bundle.policy.raw)
    raw.update(overrides)
    return dataclasses.replace(bundle, policy=Policy(raw, bundle.policy.path))


def context_for(bundle) -> GateContext:
    return GateContext(
        bundle=bundle,
        watch=WatchList(),
        computed=total_years_experience(bundle.experience, anchor=ANCHOR),
        run_date=ANCHOR,
    )


def bullet(text: str, *, role="acme", facts=("acme-f1",), metrics=(), block_id="b1") -> Block:
    return Block(
        block_type="bullet",
        text=text,
        block_id=block_id,
        role_id=role,
        fact_ids=tuple(facts),
        metric_ids=tuple(metrics),
    )


def summary(text: str, block_id="s1") -> Block:
    return Block(block_type="summary", text=text, block_id=block_id)


def skills(text: str, block_id="k1") -> Block:
    return Block(block_type="skills_line", text=text, block_id=block_id)


def document(*blocks: Block, **kwargs) -> Document:
    return Document(blocks=tuple(blocks), **kwargs)


def codes(result) -> list[str]:
    return sorted(r.code for r in result.rejections)


def assert_rejects(block, ctx, *expected_codes):
    """Assert a gate fires, and that its input still contains what it needs.

    Two claims, not one. "The gate fired" says nothing about whether the example
    still contains the thing the gate fires on, and a test that only makes the
    first claim goes green while checking nothing the moment its input drifts.
    """
    from app.gates import check_block
    from tests.preconditions import check_precondition

    for code in expected_codes:
        check_precondition(code, block, ctx)

    result = check_block(block, ctx)
    found = codes(result)
    for code in expected_codes:
        assert code in found, f"expected {code}, got {found}"
    return result


def assert_does_not_reject(block, ctx, *forbidden_codes):
    """The paired negative. No precondition: the point is that the input does
    not contain what the rule needs, or contains something that excuses it."""
    from app.gates import check_block

    result = check_block(block, ctx)
    found = codes(result)
    for code in forbidden_codes:
        assert code not in found, f"{code} fired unexpectedly: {found}"
    return result


def assert_document_rejects(document, ctx, *expected_codes):
    from app.gates.g4_structure import check_document as check_doc_level
    from tests.preconditions import check_document_precondition

    for code in expected_codes:
        check_document_precondition(code, document, ctx)

    result = check_doc_level(document, ctx)
    found = codes(result)
    for code in expected_codes:
        assert code in found, f"expected {code}, got {found}"
    return result
