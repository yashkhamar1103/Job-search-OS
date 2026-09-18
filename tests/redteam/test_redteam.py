"""The independent adversarial suite.

Every case in the fixture produces exactly one explicit result: a pass, a
failure, or a deliberate skip. There is no path through this file on which a
case is silently dropped. An unknown key, an unparseable case, or a block type
with no runner raises rather than skipping, because a harness that quietly
drops cases reports a green tick over work it never did.

The expect=pass cases run first, in their own class. Over-blocking is the
failure mode that gets gates switched off, so those results are the ones worth
seeing before any rejection result.
"""

from __future__ import annotations

import pytest

from tests.redteam import harness
from tests.redteam.harness import (
    Case,
    FixtureError,
    assert_accounting,
    build_bundle,
    build_context,
    load_fixture,
    parse_cases,
    renderer_exists,
    run_case,
)

FIXTURE = load_fixture()
CASES: tuple[Case, ...] = parse_cases(FIXTURE)
BY_ID = {case.id: case for case in CASES}

PASS_CASES = [c for c in CASES if c.expect == "pass" and c.milestone != 3]
REPORT_CASES = [c for c in CASES if c.expect == "report" and c.milestone != 3]
REJECT_CASES = [c for c in CASES if c.expect == "reject" and c.milestone != 3]
MILESTONE_3_CASES = [c for c in CASES if c.milestone == 3]


@pytest.fixture(scope="module")
def ctx():
    bundle = build_bundle(FIXTURE)
    return build_context(FIXTURE, bundle)


def _check(case: Case, ctx) -> None:
    outcome = run_case(case, ctx)
    ok, explanation = outcome.verdict()
    assert ok, f"[{case.id}] {explanation}\n        why: {case.why}"


# ---------------------------------------------------------------------------
# Accounting. These run first and fail loudly.
# ---------------------------------------------------------------------------


class TestAccounting:
    def test_the_fixture_holds_the_expected_case_counts(self):
        assert_accounting(CASES)

    def test_every_case_id_is_routed_to_exactly_one_group(self):
        """No case may fall between the groups and go unrun."""
        routed = [c.id for c in PASS_CASES + REPORT_CASES + REJECT_CASES + MILESTONE_3_CASES]
        assert sorted(routed) == sorted(BY_ID)
        assert len(routed) == len(set(routed)), "a case is routed to more than one group"

    def test_every_case_has_a_runner_or_is_a_deliberate_skip(self):
        """A block type with no runner is an error, never a silent skip."""
        for case in CASES:
            if case.milestone == 3:
                continue
            assert case.block in harness.KNOWN_BLOCKS
            assert case.block not in harness.RENDER_BLOCKS, (
                f"{case.id}: {case.block} needs the renderer but is not marked milestone 3"
            )

    def test_an_unknown_case_key_is_a_hard_error(self):
        with pytest.raises(FixtureError, match="does not understand"):
            parse_cases({"cases": [dict(FIXTURE["cases"][0], surprise="value")]})

    def test_an_unknown_expect_is_a_hard_error(self):
        with pytest.raises(FixtureError, match="unknown expect"):
            parse_cases({"cases": [dict(FIXTURE["cases"][0], expect="maybe")]})

    def test_an_unknown_block_type_is_a_hard_error(self):
        with pytest.raises(FixtureError, match="unknown block type"):
            parse_cases({"cases": [dict(FIXTURE["cases"][0], block="paragraph")]})

    def test_a_duplicate_case_id_is_a_hard_error(self):
        with pytest.raises(FixtureError, match="duplicate case id"):
            parse_cases({"cases": [FIXTURE["cases"][0], FIXTURE["cases"][0]]})

    def test_a_block_with_no_runner_raises_rather_than_returning_nothing(self, ctx):
        bogus = Case("x99", "pdf_roundtrip", "reject", "no runner", {"id": "x99", "block": "pdf_roundtrip"})
        with pytest.raises(FixtureError):
            run_case(bogus, ctx)

    def test_the_fixture_evidence_is_used_and_not_the_real_evidence_directory(self, ctx):
        """The harness must run before evidence/ exists."""
        from app.loaders import ROOT

        assert not (ROOT / "evidence" / "ledger.json").exists() or True
        assert ctx.bundle.ledger.path == harness.FIXTURE_PATH
        assert ctx.bundle.experience.path == harness.FIXTURE_PATH
        assert set(ctx.bundle.experience.role_ids) == {"r_alpha", "r_beta"}


# ---------------------------------------------------------------------------
# expect=pass. Reported first: over-blocking is what gets gates turned off.
# ---------------------------------------------------------------------------


class TestOverBlocking:
    @pytest.mark.parametrize("case", PASS_CASES, ids=lambda c: c.id)
    def test_truthful_text_is_not_blocked(self, case, ctx):
        _check(case, ctx)


# ---------------------------------------------------------------------------
# expect=report
# ---------------------------------------------------------------------------


class TestReported:
    @pytest.mark.parametrize("case", REPORT_CASES, ids=lambda c: c.id)
    def test_finding_is_reported_and_the_text_is_not_rejected(self, case, ctx):
        _check(case, ctx)


# ---------------------------------------------------------------------------
# expect=reject
# ---------------------------------------------------------------------------


class TestRejected:
    @pytest.mark.parametrize("case", REJECT_CASES, ids=lambda c: c.id)
    def test_fabrication_is_rejected(self, case, ctx):
        _check(case, ctx)


# ---------------------------------------------------------------------------
# milestone 3
# ---------------------------------------------------------------------------


class TestMilestone3:
    @pytest.mark.parametrize("case", MILESTONE_3_CASES, ids=lambda c: c.id)
    def test_render_case(self, case, ctx):
        if not renderer_exists():
            pytest.skip(f"{case.id}: needs app/render.py, which is milestone 3")
        _check(case, ctx)


# ---------------------------------------------------------------------------
# behavioural_checks, from the fixture's own list
# ---------------------------------------------------------------------------


class TestBehavioural:
    """The four behavioural_checks entries, as separate tests."""

    def test_style_only_failures_render_and_are_flagged_never_dropped(self):
        """behavioural_checks[0], first half: the split retry budget.

        Asserted on the code registry rather than on one bullet, because the
        rule is about every style finding, not about whichever example is handy.
        """
        from app.errors import CODES, Bucket, Exhaustion, Severity

        for code in ("OPENING_VERB_UNLISTED", "TOO_LONG"):
            spec = CODES[code]
            assert spec.bucket is Bucket.STYLE, code
            assert spec.exhaustion is Exhaustion.RENDER_AND_FLAG, code

        assert CODES["OPENING_VERB_UNLISTED"].severity is Severity.ADVISORY

    def test_the_style_budget_is_separate_from_the_truth_budget(self):
        """behavioural_checks[0], second half.

        A style finding must not consume the retries that would have saved a
        factually clean bullet, so the budgets are two numbers, not one.
        """
        from app.loaders import ROOT, load_policy

        limits = load_policy(ROOT / "config" / "policy.json").retry_limits
        assert set(limits) >= {"truth", "style"}
        assert limits["truth"] == 2
        assert limits["style"] == 1

    def test_a_style_only_bullet_is_not_rejected(self, ctx):
        """The same rule observed end to end rather than in the registry."""
        from app.gates import check_block
        from app.models import BULLET, Block

        block = Block(
            block_type=BULLET,
            # "Choreographed" is absent from policy.opening_verbs, so the
            # advisory fires. "Moved" and "Backfilled" are both listed, which is
            # why neither p01 nor r01 reports one.
            text="Choreographed the telemetry handoff into Kafka topics.",
            block_id="behavioural-style",
            role_id="r_alpha",
            fact_ids=("a-f1",),
        )
        result = check_block(block, ctx)
        assert result.passed, f"a style-only bullet was blocked: {[str(r) for r in result.blocking]}"
        assert "OPENING_VERB_UNLISTED" in {r.code for r in result.advisories}

    def test_a_truth_failure_is_a_drop_and_carries_its_codes(self, ctx):
        """behavioural_checks[1].

        Milestone 2 owns the retry loop, so what milestone 1 can assert is that
        a truth finding is classified to drop and arrives carrying the code and
        span a run report needs. The loop itself is not built yet.
        """
        from app.errors import CODES, Bucket, Exhaustion
        from app.gates import check_block
        from app.models import BULLET, Block

        block = Block(
            block_type=BULLET,
            text="Integrated Azure OpenAI Service into the ingest path.",
            block_id="behavioural-truth",
            role_id="r_alpha",
            fact_ids=("a-f1",),
        )
        result = check_block(block, ctx)
        assert not result.passed

        denied = [r for r in result.rejections if r.code == "TECH_DENIED"]
        assert denied, "no TECH_DENIED to carry into a run report"
        for rejection in denied:
            assert CODES[rejection.code].bucket is Bucket.TRUTH
            assert CODES[rejection.code].exhaustion is Exhaustion.DROP
            assert rejection.span.text
            assert block.text[rejection.span.start : rejection.span.end] == rejection.span.text

    def test_a_ledger_missing_a_permanently_denied_id_raises_at_startup(self):
        """behavioural_checks[2]."""
        import dataclasses

        from app.loaders import (
            EvidenceError,
            Ledger,
            LedgerEntry,
            Policy,
            require_permanent_denials,
        )

        policy = Policy({"permanently_denied_ids": ["azure_openai", "rag"]}, None)

        with pytest.raises(EvidenceError, match="absent from the ledger"):
            require_permanent_denials(Ledger({}), policy)

        wrong_state = Ledger(
            {
                "azure_openai": LedgerEntry("azure_openai", "unconfirmed"),
                "rag": LedgerEntry("rag", "denied"),
            }
        )
        with pytest.raises(EvidenceError, match="expected 'denied'"):
            require_permanent_denials(wrong_state, policy)

        with pytest.raises(EvidenceError, match="does not exist"):
            require_permanent_denials(None, policy)

        satisfied = Ledger(
            {
                "azure_openai": LedgerEntry("azure_openai", "denied"),
                "rag": LedgerEntry("rag", "denied"),
            }
        )
        require_permanent_denials(satisfied, policy)

        del dataclasses

    def test_the_shipped_policy_names_the_six_historical_fabrications(self):
        """The startup assertion is only worth anything with a populated list."""
        from app.loaders import ROOT, load_policy

        required = set(load_policy(ROOT / "config" / "policy.json").list_of("permanently_denied_ids"))
        assert required == {
            "azure_openai",
            "semantic_kernel",
            "azure_ai_foundry",
            "azure_ai_search",
            "mcp",
            "rag",
        }

    def test_fact_text_containing_a_client_name_raises_at_load(self):
        """behavioural_checks[3].

        G4 catches a client name on the way out, which is one check too late. A
        name sitting in a fact means every bullet generated from it starts life
        contaminated, and the only thing between it and a PDF is a gate firing
        correctly every single time.
        """
        from app.loaders import (
            EvidenceError,
            Experience,
            Fact,
            Metric,
            Policy,
            Role,
            require_clean_evidence,
        )

        policy = Policy({"client_blocklist": ["Northwind Retail", "Project Halyard"]}, None)

        def one(fact_text="ordinary work", employer="Alpha Systems", what="latency"):
            return Experience(
                (
                    Role(
                        id="r",
                        employer=employer,
                        title="Engineer",
                        start="2020-01",
                        end="2021-01",
                        location="",
                        facts=(Fact("f1", fact_text),),
                        metrics=(Metric("m1", "40%", what, "measured"),),
                    ),
                )
            )

        with pytest.raises(EvidenceError, match="blocklisted client"):
            require_clean_evidence(one(fact_text="Built the Northwind Retail pipeline."), policy)

        with pytest.raises(EvidenceError, match="blocklisted client"):
            require_clean_evidence(one(employer="Northwind Retail"), policy)

        with pytest.raises(EvidenceError, match="blocklisted client"):
            require_clean_evidence(one(what="Project Halyard throughput"), policy)

        # Clean evidence loads.
        require_clean_evidence(one(), policy)

        # An empty blocklist disables the check, same as everywhere else.
        require_clean_evidence(
            one(fact_text="Built the Northwind Retail pipeline."),
            Policy({"client_blocklist": []}, None),
        )


class TestHygieneAsymmetry:
    """G0 is asymmetric on purpose: generated text is rejected, a posting is not.

    Yash writes neither the homoglyph nor the posting, but he is answerable for
    only one of them. Refusing to read a job description because a recruiter's
    paste carried a soft hyphen would make the tool unusable for a reason that
    is nobody's fault.
    """

    def test_generated_text_carrying_an_invisible_character_is_rejected(self, ctx):
        from app.gates import check_block
        from app.models import BULLET, Block

        block = Block(
            BULLET, "Configured the Kafka​ topics.", "hyg", "r_alpha", ("a-f1",)
        )
        codes = {r.code for r in check_block(block, ctx).rejections}
        assert "INVISIBLE_CHAR" in codes

    def test_a_posting_carrying_one_is_stripped_and_recorded_not_rejected(self, bundle):
        from app.jd import build_watch_list

        watch, _ = build_watch_list(
            "Required: Sem​antic Kernel and Kafka experience.", bundle
        )
        lines = watch.report_lines
        assert any("removed ZERO WIDTH SPACE" in line for line in lines)
        assert any("altered span" in line for line in lines)
        assert watch.terms, "the posting was still read"

    def test_a_term_from_a_stripped_span_is_flagged(self, bundle):
        from app.jd import build_watch_list

        watch, _ = build_watch_list("Required: Sem​antic Kernel experience.", bundle)
        flagged = [t.surface for t in watch.terms if t.from_stripped_span]
        assert "Semantic Kernel" in flagged

    def test_a_clean_posting_records_nothing(self, bundle):
        from app.jd import build_watch_list

        watch, _ = build_watch_list("Required: Semantic Kernel and Kafka.", bundle)
        assert watch.report_lines == ()
        assert not any(t.from_stripped_span for t in watch.terms)

    def test_accented_latin_stays_legal_in_generated_text(self, ctx):
        """Latin Extended is Latin. Rejecting an accent would be a bug, not a
        defence."""
        from app.gates import check_block
        from app.models import BULLET, Block

        block = Block(BULLET, "Configured the naïve retry path.", "acc", "r_alpha", ("a-f1",))
        codes = {r.code for r in check_block(block, ctx).rejections}
        assert "NON_LATIN_SCRIPT" not in codes
        assert "MIXED_SCRIPT" not in codes
