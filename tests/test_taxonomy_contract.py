"""Contract tests against the real vocab/taxonomy.json.

No fixture taxonomy here. If the shipped taxonomy stops recognising a
fabrication, these fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.loaders import ROOT, load_ledger, load_taxonomy
from app.normalise import token_texts

TAXONOMY_PATH = ROOT / "vocab" / "taxonomy.json"
CONFUSABLES_PATH = ROOT / "vocab" / "confusables.json"
REAL_LEDGER_PATH = ROOT / "evidence" / "ledger.json"


#: The six claims that were added to a CV after one confirmatory sentence under
#: pressure, and were all false. Each canonical id is listed with the strings
#: that must resolve to it, including old product names, lowercase, hyphenated,
#: and plural forms.
HISTORICAL_FABRICATIONS = {
    "azure_openai": [
        "Azure OpenAI Service",
        "Azure OpenAI",
        "azure openai",
        "AZURE OPENAI",
        "AOAI",
        "aoai",
    ],
    "semantic_kernel": [
        "Semantic Kernel",
        "semantic kernel",
        "SEMANTIC KERNEL",
        "SK",
        "Microsoft Semantic Kernel",
    ],
    "azure_ai_foundry": [
        "Azure AI Foundry",
        "azure ai foundry",
        "AI Foundry",
        "Azure AI Studio",
        "azure ai studio",
        "Microsoft Foundry",
    ],
    "azure_ai_search": [
        "Azure AI Search",
        "Azure Cognitive Search",
        "azure cognitive search",
        "Cognitive Search",
        "Azure Search",
    ],
    "mcp": [
        "MCP",
        "mcp",
        "Model Context Protocol",
        "model context protocol",
        "Model-Context-Protocol",
    ],
    "rag": [
        "RAG",
        "rag",
        "Retrieval Augmented Generation",
        "retrieval-augmented generation",
        "Retrieval-Augmented Generation",
        "retrieval augmented generation",
    ],
}


@pytest.fixture(scope="module")
def taxonomy():
    return load_taxonomy(TAXONOMY_PATH)


@pytest.fixture(scope="module")
def confusables():
    return json.loads(CONFUSABLES_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "canonical_id,surface",
    [(cid, s) for cid, forms in HISTORICAL_FABRICATIONS.items() for s in forms],
)
def test_historical_fabrication_resolves(taxonomy, canonical_id, surface):
    """Every historical fabrication resolves, in every listed form.

    Against the real taxonomy, not a fixture. A term the taxonomy cannot name is
    a term no gate can reject by name.
    """
    assert taxonomy.index.resolve(surface) == canonical_id, (
        f"{surface!r} did not resolve to {canonical_id}"
    )


def test_every_alias_resolves_to_exactly_one_canonical_id(taxonomy):
    """No alias string may name two products.

    An alias shared between a confirmed id and a denied one would let the denied
    technology into output under the confirmed one's name.
    """
    seen: dict[tuple[str, ...], str] = {}
    collisions: list[str] = []
    for canonical_id in taxonomy.canonical_ids:
        for alias in taxonomy.aliases(canonical_id):
            key = token_texts(alias)
            assert key, f"alias {alias!r} under {canonical_id} has no tokens"
            if key in seen and seen[key] != canonical_id:
                collisions.append(f"{alias!r}: {seen[key]} and {canonical_id}")
            seen[key] = canonical_id
    assert not collisions, "aliases resolving to more than one id: " + "; ".join(collisions)


def test_confusable_fragments_resolve_to_nothing(taxonomy, confusables):
    """A bare fragment must name no product at all.

    Search, Kernel, and Foundry resolving to anything is how a fabrication gets
    laundered: the prefix is dropped and the remaining word carries a confirmed
    id's blessing.
    """
    resolved = {
        term: taxonomy.index.resolve(term)
        for term in confusables["must_not_resolve"]
        if taxonomy.index.resolve(term) is not None
    }
    assert not resolved, f"fragments that should name nothing resolved: {resolved}"


@pytest.mark.parametrize("term,expected", sorted(
    json.loads(CONFUSABLES_PATH.read_text(encoding="utf-8"))["must_resolve_to"].items()
))
def test_confusable_terms_resolve_to_the_right_product(taxonomy, term, expected):
    assert taxonomy.index.resolve(term) == expected


def test_no_alias_of_a_distinct_product_resolves_to_a_confirmed_id(taxonomy, confusables):
    """No pinned term may resolve to a confirmed id belonging to a different product.

    Skipped until evidence/ledger.json exists, because there is nothing confirmed
    to check against. Yash writes that file by hand.
    """
    if not REAL_LEDGER_PATH.exists():
        pytest.skip("evidence/ledger.json does not exist yet; Yash writes it by hand")

    ledger = load_ledger(REAL_LEDGER_PATH, known_ids=taxonomy.canonical_ids)
    confirmed = set(ledger.confirmed_ids)
    if not confirmed:
        pytest.skip("nothing confirmed in evidence/ledger.json yet")

    wrong: list[str] = []
    for term, expected_id in confusables["must_resolve_to"].items():
        actual = taxonomy.index.resolve(term)
        if actual != expected_id and actual in confirmed:
            wrong.append(f"{term!r} names {expected_id} but resolved to confirmed {actual}")
    for term in confusables["must_not_resolve"]:
        actual = taxonomy.index.resolve(term)
        if actual in confirmed:
            wrong.append(f"{term!r} should name nothing but resolved to confirmed {actual}")
    assert not wrong, "; ".join(wrong)


def test_ambiguous_acronyms_are_known_to_the_taxonomy(taxonomy):
    """Every configured ambiguous acronym must actually resolve.

    A check that matches nothing is a check that is not running.
    """
    from app.loaders import load_policy

    policy = load_policy(ROOT / "config" / "policy.json")
    unknown = [
        acronym
        for acronym in policy.list_of("ambiguous_acronyms")
        if taxonomy.index.resolve(acronym) is None
    ]
    assert not unknown, f"acronyms the taxonomy does not know: {unknown}"


def test_ambiguous_acronyms_cannot_be_widened_by_plural_tolerance(taxonomy):
    """Plural tolerance only applies from four characters up, so MCP, SK, and
    RAG are matched as whole tokens and nothing longer."""
    from app.gates.g1_technology import acronym_is_whole_token_only
    from app.loaders import load_policy

    policy = load_policy(ROOT / "config" / "policy.json")
    for acronym in policy.list_of("ambiguous_acronyms"):
        assert acronym_is_whole_token_only(acronym), (
            f"{acronym!r} is long enough for plural tolerance to widen it"
        )


def test_every_parent_is_a_real_entry_and_not_a_cycle(taxonomy):
    for canonical_id in taxonomy.canonical_ids:
        parent = taxonomy.parent(canonical_id)
        if parent is None:
            continue
        assert parent in taxonomy.entries
        assert parent != canonical_id
        assert taxonomy.parent(parent) != canonical_id


def test_taxonomy_is_larger_than_any_plausible_ledger(taxonomy):
    """The taxonomy lists technologies Yash does not have, on purpose."""
    assert len(taxonomy.canonical_ids) >= 250
