"""Loading, validating, and cross-checking the input files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.loaders import (
    EvidenceError,
    ROOT,
    build_corpus,
    load_bundle,
    load_experience,
    load_ledger,
    load_policy,
    load_synonyms,
    load_taxonomy,
    require_client_blocklist,
    require_default_location,
)
from app.normalise import token_texts

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = ROOT / "evidence"


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Nothing writes to evidence
# ---------------------------------------------------------------------------


def test_no_module_in_app_opens_a_file_for_writing_in_evidence():
    """Evidence files are read-only at runtime.

    A grep-level check, deliberately. It is crude, and it is the kind of rule
    that is worth catching at the moment someone writes the line rather than at
    the moment a run overwrites Yash's ledger.
    """
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for marker in ("evidence/", 'evidence_dir /'):
            if marker not in source:
                continue
            for line in source.splitlines():
                if marker in line and any(
                    w in line for w in ("write_text", "open(", "w+", '"w"', "'w'", "dump(")
                ):
                    offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, "a code path writes to evidence/: " + "; ".join(offenders)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_the_fixture_world_loads(bundle):
    assert bundle.ledger.confirmed_ids
    assert bundle.experience.role_ids == ("acme", "bolt")
    assert bundle.hashes


@pytest.mark.parametrize(
    "name,loader",
    [
        ("ledger.example.json", load_ledger),
        ("experience.example.json", load_experience),
        ("synonyms.example.json", load_synonyms),
    ],
)
def test_example_files_validate_against_their_schemas(name, loader):
    """The templates are obviously fake and still structurally valid, so a copy
    that is half edited fails on the content rather than on the shape."""
    loader(EXAMPLES / name)


def test_the_example_ledger_is_not_loadable_as_real_evidence():
    """faketech is not a canonical id, so an example left in place fails the
    loader rather than quietly becoming a claim."""
    taxonomy = load_taxonomy(ROOT / "vocab" / "taxonomy.json")
    with pytest.raises(EvidenceError, match="canonical ids"):
        load_ledger(EXAMPLES / "ledger.example.json", known_ids=taxonomy.canonical_ids)


def test_a_confirmed_entry_must_carry_its_scope(tmp_path):
    """Confirmed means it can reach output, so depth, contexts, evidence, added,
    and origin are all required."""
    path = _write(
        tmp_path,
        "ledger.json",
        {"schema_version": 1, "technologies": {"kafka": {"state": "confirmed"}}},
    )
    with pytest.raises(EvidenceError):
        load_ledger(path)


def test_an_unconfirmed_entry_may_not_carry_scope_fields(tmp_path):
    """Scope on an entry that cannot reach output is a claim no gate reads."""
    path = _write(
        tmp_path,
        "ledger.json",
        {
            "schema_version": 1,
            "technologies": {"kafka": {"state": "unconfirmed", "depth": "built"}},
        },
    )
    with pytest.raises(EvidenceError):
        load_ledger(path)


def test_a_denied_entry_may_not_carry_scope_fields(tmp_path):
    path = _write(
        tmp_path,
        "ledger.json",
        {
            "schema_version": 1,
            "technologies": {"java": {"state": "denied", "contexts": ["acme"]}},
        },
    )
    with pytest.raises(EvidenceError):
        load_ledger(path)


def test_an_unknown_state_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        "ledger.json",
        {"schema_version": 1, "technologies": {"kafka": {"state": "probably"}}},
    )
    with pytest.raises(EvidenceError):
        load_ledger(path)


def test_estimated_is_not_a_metric_source(tmp_path):
    """There is deliberately no estimated. An estimated number is not evidence."""
    path = _write(
        tmp_path,
        "experience.json",
        {
            "schema_version": 1,
            "roles": [
                {
                    "id": "acme",
                    "employer": "Acme",
                    "title": "Engineer",
                    "start": "2022-01",
                    "end": "2023-01",
                    "facts": [{"id": "f1", "text": "did a thing"}],
                    "metrics": [
                        {"id": "m1", "value": "40%", "what": "latency", "source": "estimated"}
                    ],
                }
            ],
        },
    )
    with pytest.raises(EvidenceError):
        load_experience(path)


def test_duplicate_evidence_ids_are_rejected(tmp_path):
    path = _write(
        tmp_path,
        "experience.json",
        {
            "schema_version": 1,
            "roles": [
                {
                    "id": "acme",
                    "employer": "Acme",
                    "title": "Engineer",
                    "start": "2022-01",
                    "end": "2023-01",
                    "facts": [
                        {"id": "f1", "text": "one"},
                        {"id": "f1", "text": "two"},
                    ],
                }
            ],
        },
    )
    with pytest.raises(EvidenceError, match="duplicate"):
        load_experience(path)


def test_a_synonym_without_explicit_approval_is_invalid(tmp_path):
    """approved_by_yash exists so an entry added by anything other than a
    deliberate hand edit is invalid rather than merely suspicious."""
    path = _write(
        tmp_path,
        "synonyms.json",
        {
            "schema_version": 1,
            "translations": [
                {"jd_term": "a", "evidence_term": "b", "added": "2025-01-01"}
            ],
        },
    )
    with pytest.raises(EvidenceError):
        load_synonyms(path)


# ---------------------------------------------------------------------------
# Cross-file checks
# ---------------------------------------------------------------------------


def test_a_ledger_key_outside_the_taxonomy_is_rejected(tmp_path):
    taxonomy = load_taxonomy(ROOT / "vocab" / "taxonomy.json")
    path = _write(
        tmp_path,
        "ledger.json",
        {"schema_version": 1, "technologies": {"not_a_real_id": {"state": "unconfirmed"}}},
    )
    with pytest.raises(EvidenceError, match="canonical ids"):
        load_ledger(path, known_ids=taxonomy.canonical_ids)


def test_a_context_that_is_not_a_role_id_is_rejected(tmp_path):
    payload = json.loads((FIXTURES / "ledger.json").read_text())
    payload["technologies"]["kafka"]["contexts"] = ["nowhere"]
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "ledger.json").write_text(json.dumps(payload))
    for name in ("experience.json", "synonyms.json"):
        (evidence / name).write_text((FIXTURES / name).read_text())

    with pytest.raises(EvidenceError, match="not role ids"):
        load_bundle(ROOT, evidence_dir=evidence)


def test_a_taxonomy_alias_collision_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        "taxonomy.json",
        {
            "schema_version": 1,
            "technologies": {
                "one": {"display": "One", "category": "ai", "aliases": ["Shared Name"]},
                "two": {"display": "Two", "category": "ai", "aliases": ["Shared Name"]},
            },
        },
    )
    with pytest.raises(EvidenceError, match="resolves to both"):
        load_taxonomy(path)


def test_an_unknown_parent_is_rejected(tmp_path):
    path = _write(
        tmp_path,
        "taxonomy.json",
        {
            "schema_version": 1,
            "technologies": {
                "child": {
                    "display": "Child",
                    "category": "ai",
                    "parent": "ghost",
                    "aliases": ["Child"],
                }
            },
        },
    )
    with pytest.raises(EvidenceError, match="unknown parent"):
        load_taxonomy(path)


# ---------------------------------------------------------------------------
# The evidence corpus
# ---------------------------------------------------------------------------


def test_corpus_contains_fact_text_and_confirmed_aliases(bundle):
    corpus = bundle.corpus
    assert corpus.contains(token_texts("Kafka"))
    assert corpus.contains(token_texts("ingestion"))
    assert corpus.contains(token_texts("serverless ingestion platform"))


def test_corpus_excludes_unconfirmed_aliases(bundle):
    assert not bundle.corpus.contains(token_texts("Terraform"))


def test_synonym_jd_terms_are_permitted_but_kept_out_of_the_corpus(bundle):
    """The one widening lives in a named place rather than quietly enlarging
    what every other gate treats as evidenced."""
    key = token_texts("high throughput ingestion")
    assert bundle.corpus.permitted(key)
    assert not bundle.corpus.contains(key)


def test_corpus_includes_services_of_a_confirmed_platform(bundle):
    assert bundle.corpus.contains(token_texts("Lambda"))
    assert not bundle.corpus.contains(token_texts("Redshift"))


# ---------------------------------------------------------------------------
# Policy guards
# ---------------------------------------------------------------------------


def test_policy_loads(bundle):
    assert bundle.policy["max_bullets_per_role"] == 3
    assert bundle.policy["jd_copy_ngram"] == 8
    assert bundle.policy.retry_limits == {"truth": 2, "style": 1, "schema": 1}
    assert bundle.policy["cooling_off_hours"] == 72
    assert bundle.policy["fit_threshold"] == 60


def test_the_model_id_is_not_guessed(bundle):
    """Milestone 1 calls no model. Pinning an id here would be a decision made
    without being asked for."""
    assert bundle.policy["model_id"] is None


def test_an_empty_client_blocklist_is_refused_not_silently_passed(bundle):
    with pytest.raises(EvidenceError, match="enforcing nothing"):
        require_client_blocklist(bundle.policy)


def test_an_empty_default_location_is_refused(bundle):
    with pytest.raises(EvidenceError, match="default_location"):
        require_default_location(bundle.policy)


def test_coverage_bounds_are_ordered(tmp_path):
    payload = json.loads((ROOT / "config" / "policy.json").read_text())
    payload["number_coverage_min"] = 0.95
    path = _write(tmp_path, "policy.json", payload)
    with pytest.raises(EvidenceError, match="number_coverage_min"):
        load_policy(path)


# ---------------------------------------------------------------------------
# Hashes
# ---------------------------------------------------------------------------


def test_the_run_report_gets_a_hash_of_every_input_file(bundle):
    assert set(bundle.hashes) == {
        "ledger.json",
        "experience.json",
        "synonyms.json",
        "taxonomy.json",
        "policy.json",
    }
    assert len(bundle.evidence_hash) == 64


def test_the_lexicon_loaded(bundle):
    assert len(bundle.lexicon.wordlist) > 5000
    assert "built" in bundle.lexicon.irregular_past
    assert bundle.lexicon.spell("modelled") == bundle.lexicon.spell("modeled")
