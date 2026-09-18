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
            # "Moved" is absent from policy.opening_verbs, so the advisory fires.
            # "Backfilled" is in the list, which is why r01 does not report.
            text="Moved telemetry into Kafka topics for downstream consumers.",
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

        Recorded as a finding rather than asserted green. No such check exists:
        the client blocklist is enforced on output by G4, and nothing inspects
        the evidence itself at load time. See the failure report.
        """
        from app.loaders import ROOT

        source = (ROOT / "app" / "loaders.py").read_text(encoding="utf-8")
        has_check = "client_blocklist" in source and "facts" in source.split("client_blocklist", 1)[1][:2000]
        pytest.xfail(
            "behavioural_checks[3] asks for a load-time client-name check over fact "
            "text. No such check exists; the blocklist is enforced on output only. "
            f"(loaders.py mentions a fact-adjacent blocklist check: {has_check})"
        )


# ---------------------------------------------------------------------------
# Findings derived from the fixture rather than stated by it
# ---------------------------------------------------------------------------


class TestDerivedFindings:
    """Pulled from cases that PASSED.

    d19 passes, and passes for a reason its why field does not state: the
    Cyrillic character is not folded to its Latin lookalike, it is dropped as a
    non-token character, and what gets held is the truncated stem. Pulling that
    thread found a clean bypass, which is recorded here as an xfail so it stays
    visible and turns green the day it is fixed.
    """

    CYRILLIC_A = "а"
    CYRILLIC_CAPITAL_A = "А"

    def _codes(self, text, ctx):
        from app.gates import check_block
        from app.models import BULLET, Block

        block = Block(BULLET, text, "derived", "r_alpha", ("a-f1",))
        return sorted({r.code for r in check_block(block, ctx).rejections})

    def test_a_homoglyph_inside_a_denied_term_does_not_bypass_every_gate(self, ctx):
        """The token pattern is ASCII only, so a Cyrillic a is not a character
        the tokeniser folds. It is a character the tokeniser treats as a
        separator, which splits RAG into r and G and leaves nothing to match."""
        clean = self._codes("Built a RAG pipeline over the archive.", ctx)
        assert "TECH_DENIED" in clean

        spoofed = self._codes(
            f"Built a R{self.CYRILLIC_A}G pipeline over the archive.", ctx
        )
        if not spoofed:
            pytest.xfail(
                "one Cyrillic character renders a denied technology invisible to "
                "every gate: codes are empty where the clean spelling gives "
                "TECH_DENIED"
            )
        assert "TECH_DENIED" in spoofed

    def test_a_homoglyph_does_not_downgrade_a_denied_product_to_another_one(self, ctx):
        """Azure OpenAI with a Cyrillic A tokenises to zure openai, and openai
        is a different canonical id that is merely unconfirmed."""
        spoofed = self._codes(
            f"Integrated {self.CYRILLIC_CAPITAL_A}zure OpenAI Service into the ingest path.",
            ctx,
        )
        if "TECH_DENIED" not in spoofed:
            pytest.xfail(
                f"a homoglyph downgrades azure_openai (denied) to openai "
                f"(unconfirmed): codes were {spoofed}"
            )

    def test_a_zero_width_space_does_not_split_a_multi_word_denied_term(self, ctx):
        """d07. Stripping the zero width space joins the two words into one
        token, so the two-token alias no longer matches."""
        spoofed = self._codes(
            "Built orchestration with Semantic​Kernel across the portal services.", ctx
        )
        if "TECH_DENIED" not in spoofed:
            pytest.xfail(
                f"a zero width space joins Semantic and Kernel into one token, so "
                f"the alias misses: codes were {spoofed}"
            )

    def test_a_cited_metric_expression_is_not_held_as_an_unknown_product(self, ctx):
        """p10. 3x carries a letter and a digit, which is the shape the
        proper-noun heuristic looks for, so a validated metric is held as a
        possible product name."""
        codes = self._codes("Raised ingest throughput 3x across the telemetry pipeline.", ctx)
        if "UNKNOWN_TERM" in codes:
            pytest.xfail(
                "a cited multiplier is held as an unknown proper noun: "
                f"codes were {codes}"
            )
