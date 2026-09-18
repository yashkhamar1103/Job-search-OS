"""G4, the structure and style gate."""

from __future__ import annotations

import pytest

from app import layout
from app.errors import CODES, Bucket, Severity
from app.gates import check_block, check_document
from app.gates import g4_structure
from app.gates.g4_structure import check_document as check_doc_level
from tests.conftest import (
    bullet,
    codes,
    context_for,
    document,
    skills,
    summary,
    with_policy,
)


# ---------------------------------------------------------------------------
# Bullet count
# ---------------------------------------------------------------------------


def test_more_than_three_bullets_per_role_is_rejected(ctx):
    doc = document(
        *[bullet("Configured the ingestion path.", block_id=f"b{i}") for i in range(4)]
    )
    assert "BULLET_COUNT" in codes(check_doc_level(doc, ctx))


def test_three_bullets_per_role_passes(ctx):
    doc = document(
        *[bullet("Configured the ingestion path.", block_id=f"b{i}") for i in range(3)]
    )
    assert "BULLET_COUNT" not in codes(check_doc_level(doc, ctx))


def test_the_count_is_per_role_not_per_document(ctx):
    doc = document(
        *[bullet("Configured the ingestion path.", role="acme", block_id=f"a{i}") for i in range(3)],
        *[
            bullet("Operated the reporting database.", role="bolt", facts=("bolt-f1",), block_id=f"b{i}")
            for i in range(3)
        ],
    )
    assert "BULLET_COUNT" not in codes(check_doc_level(doc, ctx))


# ---------------------------------------------------------------------------
# Banned phrases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    ["spearheaded", "championed", "drove alignment", "leveraged synergies", "owned the vision"],
)
def test_banned_phrases_are_rejected(phrase, ctx):
    result = check_block(bullet(f"Configured the path and {phrase} the rollout."), ctx)
    assert "BANNED_VERB" in codes(result)


@pytest.mark.parametrize("inflection", ["spearheading", "spearheads", "spearhead"])
def test_banned_phrase_matching_is_lemma_aware(inflection, ctx):
    result = check_block(bullet(f"Configured the path while {inflection} the rollout."), ctx)
    assert "BANNED_VERB" in codes(result)


def test_banned_phrase_matching_is_case_insensitive(ctx):
    result = check_block(bullet("Configured the path and SPEARHEADED the rollout."), ctx)
    assert "BANNED_VERB" in codes(result)


# ---------------------------------------------------------------------------
# Opening verb: a denylist, with the allowlist as coverage only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "opening",
    [
        "Responsible for the ingestion path",
        "Worked on the ingestion path",
        "Helped with the ingestion path",
        "Participated in the ingestion rollout",
        "Utilised the ingestion path",
        "Utilized the ingestion path",
        "Leveraged the ingestion path",
        "Part of the ingestion team",
        "Duties included the ingestion path",
        "In charge of the ingestion path",
    ],
)
def test_weak_openers_are_rejected(opening, ctx):
    result = check_block(bullet(f"{opening} for order events."), ctx)
    assert "WEAK_OPENING" in codes(result)


@pytest.mark.parametrize("opening", ["Building", "Quickly", "Successfully", "Managing"])
def test_ing_and_ly_openings_are_rejected(opening, ctx):
    result = check_block(bullet(f"{opening} configured the ingestion path."), ctx)
    assert "WEAK_OPENING" in codes(result)


@pytest.mark.parametrize("opening", ["Was", "Were", "Have", "Had", "Has"])
def test_be_and_have_openings_are_rejected(opening, ctx):
    result = check_block(bullet(f"{opening} configured the ingestion path."), ctx)
    assert "WEAK_OPENING" in codes(result)


def test_no_verb_in_the_first_two_tokens_is_rejected(ctx):
    result = check_block(bullet("The ingestion path for order events."), ctx)
    assert "WEAK_OPENING" in codes(result)


def test_a_verb_in_the_second_token_passes(ctx):
    result = check_block(bullet("Re configured the ingestion path."), ctx)
    assert "WEAK_OPENING" not in codes(result)


def test_multiword_opening_verb_passes(ctx):
    result = check_block(bullet("Stood up the ingestion path for order events."), ctx)
    assert "WEAK_OPENING" not in codes(result)
    assert "OPENING_VERB_UNLISTED" not in codes(result)


def test_british_and_american_spelling_share_one_entry(ctx):
    """policy.opening_verbs lists optimised once and covers both spellings."""
    british = check_block(bullet("Optimised the ingestion path for order events."), ctx)
    american = check_block(bullet("Optimized the ingestion path for order events."), ctx)
    assert "WEAK_OPENING" not in codes(british)
    assert "WEAK_OPENING" not in codes(american)
    assert "OPENING_VERB_UNLISTED" not in codes(british)
    assert "OPENING_VERB_UNLISTED" not in codes(american)


def test_an_unlisted_verb_reports_but_never_rejects(ctx):
    """The allowlist is coverage, not enforcement."""
    result = check_block(bullet("Untangled the ingestion path for order events."), ctx)
    assert "WEAK_OPENING" not in codes(result)
    assert "OPENING_VERB_UNLISTED" in codes(result)

    finding = next(r for r in result.rejections if r.code == "OPENING_VERB_UNLISTED")
    assert finding.severity is Severity.ADVISORY
    assert not finding.blocks_render
    assert result.passed, "an advisory must not fail the block"


def test_the_unlisted_finding_carries_the_exact_config_line(ctx):
    result = check_block(bullet("Untangled the ingestion path for order events."), ctx)
    finding = next(r for r in result.rejections if r.code == "OPENING_VERB_UNLISTED")
    assert finding.context["config_line"] == '  "untangled",'


# ---------------------------------------------------------------------------
# Dashes, client names, copied text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dash",
    [g4_structure.EM_DASH, g4_structure.HORIZONTAL_BAR, g4_structure.DOUBLE_HYPHEN],
)
def test_dashes_are_rejected(dash, ctx):
    result = check_block(bullet(f"Configured the path {dash} for order events."), ctx)
    assert "EM_DASH" in codes(result)


def test_client_name_in_body_text_is_rejected(bundle):
    blocked = context_for(with_policy(bundle, client_blocklist=["Northwind Traders"]))
    result = check_block(bullet("Configured the path for Northwind Traders."), blocked)
    assert "CLIENT_NAME" in codes(result)


def test_client_name_matching_is_whole_word(bundle):
    blocked = context_for(with_policy(bundle, client_blocklist=["Ace"]))
    result = check_block(bullet("Configured the path to trace order events."), blocked)
    assert "CLIENT_NAME" not in codes(result)


def test_client_name_in_filename_and_metadata_is_rejected(bundle):
    blocked = context_for(with_policy(bundle, client_blocklist=["Northwind Traders"]))
    doc = document(
        bullet("Configured the ingestion path."),
        filename_stem="Northwind_Traders_Engineer_Resume",
        metadata={"subject": "Prepared for Northwind Traders"},
    )
    found = codes(check_doc_level(doc, blocked))
    assert found.count("CLIENT_NAME") == 2


def test_an_empty_client_blocklist_is_caught_at_load_not_silently_passed(bundle):
    """An empty blocklist makes CLIENT_NAME match nothing, which is fail-open.

    The gate cannot tell an empty list from a satisfied one, so the loader is
    what must refuse. This test pins the current state: the list ships empty
    because the names are Yash's to supply, and `require_client_blocklist`
    is what a run calls before trusting the check.
    """
    from app.loaders import require_client_blocklist, EvidenceError

    with pytest.raises(EvidenceError):
        require_client_blocklist(bundle.policy)

    ok = with_policy(bundle, client_blocklist=["Northwind Traders"])
    require_client_blocklist(ok.policy)


def test_eight_shared_words_with_the_job_description_are_rejected(ctx_with_jd):
    shared = "design and operate resilient data pipelines across the platform"
    ctx = ctx_with_jd(f"You will {shared} every day.")
    result = check_block(bullet(f"Configured {shared} for order events."), ctx)
    assert "JD_COPY" in codes(result)


def test_seven_shared_words_pass(ctx_with_jd):
    shared = "operate resilient data pipelines across the platform"
    ctx = ctx_with_jd(f"You will {shared} every day.")
    result = check_block(bullet(f"Configured {shared} today."), ctx)
    assert "JD_COPY" not in codes(result)


# ---------------------------------------------------------------------------
# Rendered length
# ---------------------------------------------------------------------------


def test_a_short_bullet_passes(ctx):
    result = check_block(bullet("Configured the ingestion path for order events."), ctx)
    assert "TOO_LONG" not in codes(result)


def test_a_bullet_over_three_rendered_lines_is_rejected(ctx):
    long_text = "Configured the ingestion path for order events " * 8
    result = check_block(bullet(long_text.strip() + "."), ctx)
    assert "TOO_LONG" in codes(result)


def test_a_summary_over_four_rendered_lines_is_rejected(ctx):
    long_text = "Backend engineer working across ingestion and reporting systems " * 8
    result = check_block(summary(long_text.strip() + "."), ctx)
    assert "TOO_LONG" in codes(result)


def test_length_is_measured_on_the_marked_up_text(ctx):
    """Bold runs are wider. Measuring the stripped string would let a bolded
    bullet overflow by a word."""
    from app.models import Block

    words = "Configured the ingestion path for order events across every region " * 2
    plain = Block(block_type="bullet", text=words, block_id="b1", role_id="acme", fact_ids=("acme-f1",))
    bolded = Block(
        block_type="bullet",
        text=words,
        block_id="b2",
        role_id="acme",
        fact_ids=("acme-f1",),
        markup=f"<b>{layout.escape_markup(words)}</b>",
    )
    assert layout.measure_lines("bullet", bolded.measurable_markup) >= layout.measure_lines(
        "bullet", plain.measurable_markup
    )


# ---------------------------------------------------------------------------
# Skills section
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "qualifier", ["Expert", "Advanced", "Proficient", "Intermediate", "Familiar", "Basic"]
)
def test_proficiency_qualifiers_are_rejected_in_skills(qualifier, ctx):
    result = check_block(skills(f"Languages: Python ({qualifier})"), ctx)
    assert "SKILLS_PROFICIENCY" in codes(result)


def test_multiword_proficiency_qualifier_is_rejected(ctx):
    result = check_block(skills("Languages: Python, working knowledge of Kafka"), ctx)
    assert "SKILLS_PROFICIENCY" in codes(result)


def test_years_construction_is_rejected_in_skills(ctx):
    result = check_block(skills("Languages: Python, 5 years"), ctx)
    assert "SKILLS_PROFICIENCY" in codes(result)


def test_a_plain_skills_line_passes(ctx):
    result = check_block(skills("Languages: Python"), ctx)
    assert result.passed, codes(result)


# ---------------------------------------------------------------------------
# Retry buckets
# ---------------------------------------------------------------------------


def test_truth_findings_drop_and_style_findings_render_and_flag():
    """A style rule must never drop a factually clean bullet."""
    for code in ("TECH_DENIED", "TECH_UNCONFIRMED", "JD_TERM_NOT_IN_EVIDENCE",
                 "SCOPE_DEPTH", "SCOPE_CONTEXT", "SCOPE_SERVICE", "SCOPE_COHABITATION",
                 "NUMBER_UNSUPPORTED", "VAGUE_METRIC", "CLIENT_NAME", "JD_COPY", "EM_DASH"):
        assert CODES[code].bucket is Bucket.TRUTH, code
        assert CODES[code].exhaustion.value == "drop", code

    for code in ("OPENING_VERB_UNLISTED", "TOO_LONG", "BANNED_VERB", "WEAK_OPENING"):
        assert CODES[code].bucket is Bucket.STYLE, code
        assert CODES[code].exhaustion.value == "render_and_flag", code


def test_held_items_never_render_unapproved():
    assert CODES["UNKNOWN_TERM"].severity is Severity.HOLD
    assert CODES["UNKNOWN_TERM"].exhaustion.value == "hold_for_review"


def test_document_check_runs_every_gate(ctx):
    doc = document(
        bullet("Wrote a RAG pipeline on Azure OpenAI."),
        summary("Backend engineer who cut latency by 40%."),
        skills("Cloud: Semantic Kernel"),
    )
    found = codes(check_document(doc, ctx))
    assert "TECH_DENIED" in found
    assert "UNCITED_NUMBER" in found
