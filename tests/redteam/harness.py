"""Loading and running the independent adversarial fixture.

The fixture was authored outside the session that wrote the gates, which is the
only reason it is worth anything. So this module adapts to the fixture rather
than the other way round, and it never edits a case.

Two consequences of that, both deliberate:

The fixture's evidence block is loaded instead of `evidence/`. The harness runs
before the real evidence files exist and must never depend on them.

The fixture's ledger entries carry no `evidence`, `added`, or `origin` fields,
which the project's own ledger schema requires of a confirmed entry. The objects
are therefore constructed directly rather than validated through that schema.
Relaxing the schema to accept the fixture would be editing the project to suit
the test, which is the move the fixture exists to catch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from app.computed import total_years_experience
from app.errors import GateResult
from app.gates import check_block, check_document
from app.gates.context import GateContext
from app.jd import build_watch_list
from app.loaders import (
    ROOT,
    Bundle,
    Experience,
    Fact,
    Ledger,
    LedgerEntry,
    Metric,
    Policy,
    Role,
    Synonyms,
    build_corpus,
    load_lexicon,
    load_policy,
    load_taxonomy,
)
from app.models import BULLET, SKILLS_LINE, SUMMARY, Block, Document

FIXTURE_PATH = Path(__file__).parent / "redteam_fixture.json"

#: Asserted at load, fixture version 3. A fixture that grew or shrank silently
#: is a fixture whose coverage nobody is tracking.
EXPECTED_TOTAL = 74
EXPECTED_BY_EXPECT = {"reject": 57, "pass": 15, "report": 2}
EXPECTED_MILESTONE_3 = 3

#: Every key the harness understands. An unrecognised key is a hard error: the
#: reviewer may have encoded an instruction this runner is quietly ignoring.
KNOWN_CASE_KEYS = frozenset(
    {"id", "block", "role", "text", "cites", "expect", "codes", "why", "milestone", "bullets", "field"}
)
KNOWN_CITE_KEYS = frozenset({"fact_ids", "metric_ids"})
KNOWN_EXPECT = frozenset({"reject", "pass", "report"})

#: The fixture's block vocabulary, mapped onto the project's block types.
BLOCK_TYPES = {"bullet": BULLET, "summary": SUMMARY, "skills": SKILLS_LINE}
DOCUMENT_BLOCKS = frozenset({"role_set"})
RENDER_BLOCKS = frozenset({"filename", "docx_metadata", "pdf_roundtrip"})
KNOWN_BLOCKS = frozenset(BLOCK_TYPES) | DOCUMENT_BLOCKS | RENDER_BLOCKS

#: Both fixture roles have end dates, so the anchor cannot move the computed
#: years. Pinned anyway so a reader does not have to work that out.
ANCHOR = date(2026, 1, 1)


class FixtureError(Exception):
    """The fixture is not shaped the way this harness understands.

    Always fatal. A harness that skips what it cannot parse under-reports, and
    an under-reporting red team harness is worse than none: it produces a green
    tick over cases nobody ran.
    """


@dataclass(frozen=True)
class Case:
    id: str
    block: str
    expect: str
    why: str
    raw: dict[str, Any]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(self.raw.get("codes", ()))

    @property
    def milestone(self) -> int:
        return int(self.raw.get("milestone", 1))

    @property
    def text(self) -> str:
        return self.raw.get("text", "")


@dataclass(frozen=True)
class Outcome:
    """What running one case produced. Never None, never absent."""

    case: Case
    codes: tuple[str, ...]
    advisory_codes: tuple[str, ...]
    passed: bool
    """True when nothing in the result blocks rendering."""

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(c for c in self.case.codes if c not in self.codes)

    @property
    def unexpected(self) -> tuple[str, ...]:
        return tuple(c for c in self.codes if c not in self.case.codes)

    def verdict(self) -> tuple[bool, str]:
        """(ok, explanation)."""
        if self.case.expect == "reject":
            if self.missing:
                return False, (
                    f"expected {list(self.case.codes)}, returned {list(self.codes)}; "
                    f"missing {list(self.missing)}"
                )
            return True, f"returned {list(self.codes)}"
        if self.case.expect == "pass":
            # Fixture version 2: pass means not rejected and no truth or style
            # code. An advisory is allowed and is printed rather than hidden,
            # because an advisory firing on truthful text is information, not a
            # failure.
            blocking = [c for c in self.codes if c not in self.advisory_codes]
            if blocking or not self.passed:
                return False, f"expected no blocking codes, returned {blocking}"
            if self.advisory_codes:
                return True, f"not rejected; advisories {list(self.advisory_codes)}"
            return True, "no codes"
        if self.case.expect == "report":
            missing = [c for c in self.case.codes if c not in self.advisory_codes]
            if missing:
                return False, (
                    f"expected {list(self.case.codes)} as a report, "
                    f"advisories were {list(self.advisory_codes)}, "
                    f"all codes {list(self.codes)}"
                )
            if not self.passed:
                return False, (
                    f"reported {list(self.case.codes)} but the text was also rejected: "
                    f"{list(self.codes)}"
                )
            return True, f"reported {list(self.advisory_codes)}, not rejected"
        raise FixtureError(f"{self.case.id}: unknown expect {self.case.expect!r}")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


#: Top-level keys the harness understands. Same rule as for case keys: an
#: unrecognised one is a hard error rather than something quietly ignored.
KNOWN_FIXTURE_KEYS = frozenset(
    {"fixture_version", "amended_by", "purpose", "rules_for_harness", "evidence",
     "cases", "behavioural_checks"}
)
SUPPORTED_FIXTURE_VERSION = 3


def load_fixture(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    if not path.exists():
        raise FixtureError(f"fixture not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))

    unknown = sorted(set(data) - KNOWN_FIXTURE_KEYS)
    if unknown:
        raise FixtureError(f"fixture carries unknown top-level keys: {unknown}")
    if data.get("fixture_version") != SUPPORTED_FIXTURE_VERSION:
        raise FixtureError(
            f"fixture_version {data.get('fixture_version')!r}, harness supports "
            f"{SUPPORTED_FIXTURE_VERSION}"
        )
    return data


def parse_cases(fixture: dict[str, Any]) -> tuple[Case, ...]:
    raw_cases = fixture.get("cases")
    if not isinstance(raw_cases, list):
        raise FixtureError("fixture has no cases list")

    seen: set[str] = set()
    cases: list[Case] = []
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise FixtureError(f"case at index {index} is not an object")

        unknown = sorted(set(raw) - KNOWN_CASE_KEYS)
        if unknown:
            raise FixtureError(
                f"case {raw.get('id', index)!r} carries keys this harness does not "
                f"understand: {unknown}. Refusing to run it while ignoring them."
            )
        for required in ("id", "block", "expect", "why"):
            if required not in raw:
                raise FixtureError(f"case at index {index} has no {required!r}")

        case_id = raw["id"]
        if case_id in seen:
            raise FixtureError(f"duplicate case id {case_id!r}")
        seen.add(case_id)

        if raw["expect"] not in KNOWN_EXPECT:
            raise FixtureError(f"{case_id}: unknown expect {raw['expect']!r}")
        if raw["block"] not in KNOWN_BLOCKS:
            raise FixtureError(f"{case_id}: unknown block type {raw['block']!r}")
        if raw["expect"] in ("reject", "report") and not raw.get("codes"):
            raise FixtureError(f"{case_id}: expect={raw['expect']} with no codes")

        cites = raw.get("cites", {})
        if not isinstance(cites, dict):
            raise FixtureError(f"{case_id}: cites is not an object")
        unknown_cites = sorted(set(cites) - KNOWN_CITE_KEYS)
        if unknown_cites:
            raise FixtureError(f"{case_id}: unknown cites keys {unknown_cites}")

        cases.append(Case(case_id, raw["block"], raw["expect"], raw["why"], raw))

    return tuple(cases)


def assert_accounting(cases: Iterable[Case]) -> None:
    cases = tuple(cases)
    if len(cases) != EXPECTED_TOTAL:
        raise FixtureError(f"expected {EXPECTED_TOTAL} cases, found {len(cases)}")

    counts: dict[str, int] = {}
    for case in cases:
        counts[case.expect] = counts.get(case.expect, 0) + 1
    if counts != EXPECTED_BY_EXPECT:
        raise FixtureError(f"expected {EXPECTED_BY_EXPECT} by expect, found {counts}")

    milestone_3 = sum(1 for c in cases if c.milestone == 3)
    if milestone_3 != EXPECTED_MILESTONE_3:
        raise FixtureError(
            f"expected {EXPECTED_MILESTONE_3} milestone 3 cases, found {milestone_3}"
        )


# ---------------------------------------------------------------------------
# Building a bundle from the fixture's own evidence
# ---------------------------------------------------------------------------


def build_bundle(fixture: dict[str, Any]) -> Bundle:
    evidence = fixture["evidence"]

    taxonomy = load_taxonomy(ROOT / "vocab" / "taxonomy.json")
    lexicon = load_lexicon(ROOT / "vocab")

    raw_policy = dict(load_policy(ROOT / "config" / "policy.json").raw)
    overrides = evidence.get("policy_overrides", {})
    unknown_overrides = sorted(set(overrides) - set(raw_policy))
    if unknown_overrides:
        raise FixtureError(
            f"policy_overrides names keys the policy schema does not have: "
            f"{unknown_overrides}"
        )
    raw_policy.update(overrides)
    policy = Policy(raw_policy, ROOT / "config" / "policy.json")

    entries: dict[str, LedgerEntry] = {}
    for canonical_id, raw in evidence["ledger"].items():
        if canonical_id not in taxonomy.entries:
            raise FixtureError(
                f"fixture ledger names {canonical_id!r}, which is not a canonical id "
                f"in vocab/taxonomy.json"
            )
        entries[canonical_id] = LedgerEntry(
            canonical_id=canonical_id,
            state=raw["state"],
            depth=raw.get("depth"),
            contexts=tuple(raw.get("contexts", ())),
            scope_note=raw.get("scope_note", ""),
            versions=tuple(raw.get("versions", ())),
            services=tuple(raw.get("services", ())),
            evidence=raw.get("evidence", ""),
            added=raw.get("added", ""),
            origin=raw.get("origin", ""),
        )
    ledger = Ledger(entries, FIXTURE_PATH)

    roles: list[Role] = []
    for raw_role in evidence["experience"]["roles"]:
        roles.append(
            Role(
                id=raw_role["id"],
                employer=raw_role["employer"],
                title=raw_role["title"],
                start=raw_role["start"],
                end=raw_role.get("end"),
                location=raw_role.get("location", ""),
                facts=tuple(Fact(f["id"], f["text"]) for f in raw_role.get("facts", ())),
                metrics=tuple(
                    Metric(m["id"], m["value"], m["what"], m["source"], m.get("note", ""))
                    for m in raw_role.get("metrics", ())
                ),
            )
        )
    experience = Experience(tuple(roles), FIXTURE_PATH)

    raw_synonyms = evidence.get("synonyms") or {}
    if raw_synonyms:
        raise FixtureError(
            "fixture carries synonyms, which this harness does not yet translate"
        )
    synonyms = Synonyms((), FIXTURE_PATH)

    corpus = build_corpus(ledger, experience, synonyms, taxonomy)
    return Bundle(ledger, experience, synonyms, taxonomy, policy, lexicon, corpus, {})


def build_context(fixture: dict[str, Any], bundle: Bundle) -> GateContext:
    watch, _ = build_watch_list(fixture["evidence"]["jd_text"], bundle)
    return GateContext(
        bundle=bundle,
        watch=watch,
        computed=total_years_experience(bundle.experience, anchor=ANCHOR),
        run_date=ANCHOR,
    )


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def _cites(case: Case) -> tuple[tuple[str, ...], tuple[str, ...]]:
    cites = case.raw.get("cites", {})
    return tuple(cites.get("fact_ids", ())), tuple(cites.get("metric_ids", ()))


def run_case(case: Case, ctx: GateContext) -> Outcome:
    """Run one case. Raises rather than returning nothing."""
    if case.milestone == 3:
        raise FixtureError(f"{case.id}: milestone 3 cases are skipped, not run")

    facts, metrics = _cites(case)

    if case.block in BLOCK_TYPES:
        block = Block(
            block_type=BLOCK_TYPES[case.block],
            text=case.text,
            block_id=case.id,
            role_id=case.raw.get("role"),
            fact_ids=facts,
            metric_ids=metrics,
        )
        result: GateResult = check_block(block, ctx)
    elif case.block == "role_set":
        bullets = case.raw.get("bullets")
        if not bullets:
            raise FixtureError(f"{case.id}: role_set case has no bullets")
        document = Document(
            blocks=tuple(
                Block(
                    block_type=BULLET,
                    text=text,
                    block_id=f"{case.id}-{i}",
                    role_id=case.raw.get("role"),
                    fact_ids=facts,
                    metric_ids=metrics,
                )
                for i, text in enumerate(bullets)
            )
        )
        result = check_document(document, ctx)
    else:
        raise FixtureError(f"{case.id}: block {case.block!r} has no runner")

    return Outcome(
        case=case,
        codes=tuple(sorted({r.code for r in result.rejections})),
        advisory_codes=tuple(sorted({r.code for r in result.advisories})),
        passed=result.passed,
    )


def renderer_exists() -> bool:
    try:
        import app.render  # noqa: F401
    except ImportError:
        return False
    return True
