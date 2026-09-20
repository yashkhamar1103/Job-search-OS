"""The incident this system exists to prevent, replayed end to end.

Six technology claims were added to a CV after one confirmatory sentence under
pressure. All six were false. This test drives a whole document through every
gate with a job description that asks for all six, which is the exact shape of
the pressure: the posting wants them, the model can write them, and nothing in
the evidence supports them.
"""

from __future__ import annotations

from app.gates import check_document
from app.jd import build_watch_list
from tests.conftest import bullet, codes, document, skills, summary

JOB_DESCRIPTION = """
Senior AI Platform Engineer

We are looking for an engineer with deep, hands-on experience across our
generative AI stack. You will design and operate retrieval augmented generation
pipelines in production.

Required:
- Azure OpenAI Service, including prompt and token management
- Semantic Kernel for orchestration
- Azure AI Foundry, formerly Azure AI Studio
- Azure AI Search, formerly Azure Cognitive Search
- Model Context Protocol (MCP) server development
- Retrieval augmented generation at code level
- Chronosphere for observability
- Strong Python and Kafka background
"""


def test_the_full_fabrication_does_not_survive_the_gates(ctx_with_jd):
    """The CV a model would happily write if nothing stopped it."""
    ctx = ctx_with_jd(JOB_DESCRIPTION)

    doc = document(
        summary(
            "AI platform engineer with deep experience in retrieval augmented "
            "generation and Azure OpenAI across production systems."
        ),
        bullet(
            "Built RAG pipelines on Azure OpenAI Service with Semantic Kernel "
            "for orchestration.",
            block_id="b1",
        ),
        bullet(
            "Designed MCP servers backed by Azure AI Search for retrieval.",
            block_id="b2",
        ),
        bullet(
            "Deployed models through Azure AI Foundry for the platform team.",
            block_id="b3",
        ),
        skills("AI: Azure OpenAI, Semantic Kernel, MCP, RAG, Azure AI Search"),
    )

    result = check_document(doc, ctx)
    found = codes(result)

    assert not result.passed
    assert "TECH_DENIED" in found

    denied_terms = {
        r.context.get("canonical_id") for r in result.rejections if r.code == "TECH_DENIED"
    }
    assert denied_terms == {
        "azure_openai",
        "semantic_kernel",
        "azure_ai_foundry",
        "azure_ai_search",
        "mcp",
        "rag",
    }, f"a historical fabrication survived: {denied_terms}"


def test_an_unknown_posting_term_is_caught_even_though_the_taxonomy_never_heard_of_it(
    ctx_with_jd,
):
    """Chronosphere is in the posting and in no evidence file. The taxonomy does
    not know it either, which is exactly the case the watch list exists for."""
    ctx = ctx_with_jd(JOB_DESCRIPTION)
    doc = document(bullet("Configured Chronosphere dashboards for the platform."))
    found = codes(check_document(doc, ctx))
    assert "JD_TERM_NOT_IN_EVIDENCE" in found


def test_a_truthful_cv_against_the_same_posting_passes(ctx_with_jd):
    """The system is not simply strict. A CV that claims only what the evidence
    supports must get through, or the gates would just be a wall."""
    ctx = ctx_with_jd(JOB_DESCRIPTION)

    doc = document(
        summary(
            f"Backend engineer with {ctx.computed.total_years} years building "
            f"ingestion and reporting systems."
        ),
        bullet(
            "Configured Kafka producers that published order events onto the cluster.",
            block_id="b1",
            role="acme",
            facts=("acme-f2",),
        ),
        bullet(
            "Reduced ingestion latency by 40% across the platform.",
            block_id="b2",
            role="acme",
            facts=("acme-f1",),
            metrics=("acme-m1",),
        ),
        bullet(
            "Operated the reporting database behind the service.",
            block_id="b3",
            role="bolt",
            facts=("bolt-f1",),
        ),
        skills("Languages: Python"),
    )

    result = check_document(doc, ctx)
    assert result.passed, f"a truthful CV was blocked: {[str(r) for r in result.blocking]}"


def test_every_rejection_names_a_registered_code_and_a_real_span(ctx_with_jd):
    """A finding the run report cannot render is a finding nobody acts on."""
    from app.errors import CODES

    ctx = ctx_with_jd(JOB_DESCRIPTION)
    doc = document(
        bullet("Built RAG pipelines on Azure OpenAI with Semantic Kernel."),
        summary("Engineer who significantly improved throughput by 90%."),
        skills("AI: MCP, expert level"),
    )
    result = check_document(doc, ctx)
    assert result.rejections

    by_id = {b.block_id: b for b in doc.blocks}
    for rejection in result.rejections:
        assert rejection.code in CODES
        assert rejection.spec.description
        block = by_id.get(rejection.block_id)
        if block is None:
            continue
        assert block.text[rejection.span.start : rejection.span.end] == rejection.span.text


def test_the_run_report_can_state_what_produced_the_document(bundle):
    """Evidence hash and layout version, so a CV can be traced back to the
    inputs and the geometry that produced it."""
    from app import layout

    assert len(bundle.evidence_hash) == 64
    assert isinstance(layout.LAYOUT_VERSION, int)
    assert set(bundle.hashes) >= {"ledger.json", "experience.json", "synonyms.json"}


def test_the_watch_list_is_built_before_any_model_sees_the_posting(bundle):
    """build_watch_list takes the posting and the loaded files, and nothing
    else. There is no model client to pass it even if someone wanted to."""
    import inspect

    from app import jd

    signature = inspect.signature(build_watch_list)
    assert list(signature.parameters) == ["jd_text", "bundle"]
    source = inspect.getsource(jd)
    for forbidden in ("anthropic", "openai", "requests", "httpx", "urllib"):
        assert forbidden not in source.lower()


def test_no_gate_imports_a_model_client_or_a_network_library():
    """Gates are deterministic code. Every constraint is enforced by pure
    functions that read only their inputs and the loaded evidence."""
    import inspect

    from app.gates import GATES
    from app.gates import context as gate_context

    for module in (*GATES, gate_context):
        source = inspect.getsource(module)
        for forbidden in ("anthropic", "openai", "requests", "httpx", "urllib", "socket"):
            assert forbidden not in source.lower(), (
                f"{module.__name__} references {forbidden}"
            )
