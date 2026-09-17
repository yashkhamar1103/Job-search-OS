"""Loading and validating the evidence, vocabulary, policy, and lexicon files.

Nothing here writes. There is no code path in this module, or reachable from it,
that opens a file in evidence/ for writing. Evidence changes are made by hand,
in git, outside any tailoring run.

Two states are deliberately distinguished, and they are not the same question:

    state_of(id)       Can this appear in output? An id absent from the ledger
                       is unconfirmed, so the answer is no.

    is_suggestable(id) May Step 1 name this as a gap Yash could go and verify?
                       Only an entry the ledger explicitly marks unconfirmed.
                       An id absent from the ledger is blocked and is never
                       suggested, so the app cannot hand back a shopping list of
                       technologies to go and acquire.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from jsonschema import Draft202012Validator

from app.normalise import AliasIndex, normalise_spelling, token_texts

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

CONFIRMED = "confirmed"
UNCONFIRMED = "unconfirmed"
DENIED = "denied"

#: Longest phrase indexed when asking whether a term is in the evidence corpus.
_MAX_CORPUS_PHRASE = 8


class EvidenceError(Exception):
    """A file on disk is invalid. Always fatal: the run does not start."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise EvidenceError(f"missing file: {path}") from None
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"{path} is not valid JSON: {exc}") from None


def _validate(data: Any, schema_name: str, path: Path) -> None:
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        lines = [f"{path} failed {schema_name}:"]
        for err in errors[:20]:
            where = "/".join(str(p) for p in err.path) or "(root)"
            lines.append(f"  {where}: {err.message}")
        raise EvidenceError("\n".join(lines))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerEntry:
    canonical_id: str
    state: str
    depth: str | None = None
    contexts: tuple[str, ...] = ()
    scope_note: str = ""
    versions: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    evidence: str = ""
    added: str = ""
    origin: str = ""

    @property
    def confirmed(self) -> bool:
        return self.state == CONFIRMED

    @property
    def added_date(self) -> date | None:
        return date.fromisoformat(self.added) if self.added else None


@dataclass(frozen=True)
class Ledger:
    entries: Mapping[str, LedgerEntry]
    path: Path | None = None

    def get(self, canonical_id: str) -> LedgerEntry | None:
        return self.entries.get(canonical_id)

    def state_of(self, canonical_id: str) -> str:
        """The gating state. An id the ledger does not mention is unconfirmed."""
        entry = self.entries.get(canonical_id)
        return entry.state if entry else UNCONFIRMED

    def is_confirmed(self, canonical_id: str) -> bool:
        return self.state_of(canonical_id) == CONFIRMED

    def is_denied(self, canonical_id: str) -> bool:
        return self.state_of(canonical_id) == DENIED

    def is_suggestable(self, canonical_id: str) -> bool:
        """May Step 1 name this as a gap Yash could verify?

        Only an entry explicitly written as unconfirmed. Absence from the ledger
        is not an invitation.
        """
        entry = self.entries.get(canonical_id)
        return entry is not None and entry.state == UNCONFIRMED

    @property
    def confirmed_ids(self) -> tuple[str, ...]:
        return tuple(sorted(cid for cid, e in self.entries.items() if e.confirmed))

    @property
    def denied_ids(self) -> tuple[str, ...]:
        return tuple(sorted(cid for cid, e in self.entries.items() if e.state == DENIED))


def load_ledger(path: Path, *, known_ids: Iterable[str] | None = None) -> Ledger:
    data = _read_json(path)
    _validate(data, "ledger.schema.json", path)
    entries: dict[str, LedgerEntry] = {}
    for canonical_id, raw in data["technologies"].items():
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
    if known_ids is not None:
        known = set(known_ids)
        unknown = sorted(set(entries) - known)
        if unknown:
            raise EvidenceError(
                f"{path}: ledger keys are not canonical ids in the taxonomy: "
                + ", ".join(unknown)
            )
    return Ledger(entries, path)


# ---------------------------------------------------------------------------
# Experience
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    id: str
    text: str


@dataclass(frozen=True)
class Metric:
    id: str
    value: str
    what: str
    source: str
    note: str = ""

    @property
    def recalled(self) -> bool:
        return self.source == "recalled"


@dataclass(frozen=True)
class Role:
    id: str
    employer: str
    title: str
    start: str
    end: str | None
    location: str
    facts: tuple[Fact, ...]
    metrics: tuple[Metric, ...]

    @property
    def is_current(self) -> bool:
        return self.end in (None, "", "present")


@dataclass(frozen=True)
class Experience:
    roles: tuple[Role, ...]
    path: Path | None = None

    @property
    def role_ids(self) -> tuple[str, ...]:
        return tuple(r.id for r in self.roles)

    def role(self, role_id: str) -> Role | None:
        for r in self.roles:
            if r.id == role_id:
                return r
        return None

    @property
    def facts_by_id(self) -> dict[str, Fact]:
        return {f.id: f for r in self.roles for f in r.facts}

    @property
    def metrics_by_id(self) -> dict[str, Metric]:
        return {m.id: m for r in self.roles for m in r.metrics}


def load_experience(path: Path) -> Experience:
    data = _read_json(path)
    _validate(data, "experience.schema.json", path)
    roles: list[Role] = []
    seen_ids: set[str] = set()
    for raw in data["roles"]:
        facts = tuple(Fact(f["id"], f["text"]) for f in raw["facts"])
        metrics = tuple(
            Metric(m["id"], m["value"], m["what"], m["source"], m.get("note", ""))
            for m in raw.get("metrics", ())
        )
        for item in (*facts, *metrics):
            if item.id in seen_ids:
                raise EvidenceError(f"{path}: duplicate evidence id {item.id!r}")
            seen_ids.add(item.id)
        if raw["id"] in {r.id for r in roles}:
            raise EvidenceError(f"{path}: duplicate role id {raw['id']!r}")
        roles.append(
            Role(
                id=raw["id"],
                employer=raw["employer"],
                title=raw["title"],
                start=raw["start"],
                end=raw.get("end"),
                location=raw.get("location", ""),
                facts=facts,
                metrics=metrics,
            )
        )
    return Experience(tuple(roles), path)


# ---------------------------------------------------------------------------
# Synonyms
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Translation:
    jd_term: str
    evidence_term: str
    scope_note: str = ""
    added: str = ""


@dataclass(frozen=True)
class Synonyms:
    translations: tuple[Translation, ...] = ()
    path: Path | None = None

    @property
    def jd_terms(self) -> tuple[str, ...]:
        return tuple(t.jd_term for t in self.translations)

    @property
    def evidence_terms(self) -> tuple[str, ...]:
        return tuple(t.evidence_term for t in self.translations)


def load_synonyms(path: Path) -> Synonyms:
    data = _read_json(path)
    _validate(data, "synonyms.schema.json", path)
    return Synonyms(
        tuple(
            Translation(
                jd_term=t["jd_term"],
                evidence_term=t["evidence_term"],
                scope_note=t.get("scope_note", ""),
                added=t.get("added", ""),
            )
            for t in data["translations"]
        ),
        path,
    )


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Taxonomy:
    entries: Mapping[str, dict]
    index: AliasIndex
    path: Path | None = None

    @property
    def canonical_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.entries))

    def aliases(self, canonical_id: str) -> tuple[str, ...]:
        return tuple(self.entries[canonical_id]["aliases"])

    def display(self, canonical_id: str) -> str:
        entry = self.entries.get(canonical_id)
        return entry["display"] if entry else canonical_id

    def parent(self, canonical_id: str) -> str | None:
        entry = self.entries.get(canonical_id)
        return entry.get("parent") if entry else None

    def alias_keys(self, canonical_id: str) -> frozenset[tuple[str, ...]]:
        """Every alias of an id as a token tuple, plus its display name.

        Used to decide whether a platform's services list names this id, since
        a services list is written in product names rather than canonical ids.
        """
        entry = self.entries.get(canonical_id)
        if not entry:
            return frozenset()
        keys = {token_texts(a) for a in entry["aliases"]}
        keys.add(token_texts(entry["display"]))
        keys.add(token_texts(canonical_id.replace("_", " ")))
        return frozenset(k for k in keys if k)


def load_taxonomy(path: Path) -> Taxonomy:
    data = _read_json(path)
    _validate(data, "taxonomy.schema.json", path)
    entries = data["technologies"]

    seen: dict[str, str] = {}
    for canonical_id, entry in entries.items():
        for alias in entry["aliases"]:
            key = " ".join(token_texts(alias))
            if not key:
                raise EvidenceError(f"{path}: alias {alias!r} under {canonical_id} has no tokens")
            if key in seen and seen[key] != canonical_id:
                raise EvidenceError(
                    f"{path}: alias {alias!r} resolves to both {seen[key]} and {canonical_id}"
                )
            seen[key] = canonical_id

    for canonical_id, entry in entries.items():
        walker = entry.get("parent")
        depth = 0
        while walker is not None:
            if walker not in entries:
                raise EvidenceError(f"{path}: {canonical_id} has unknown parent {walker!r}")
            if walker == canonical_id:
                raise EvidenceError(f"{path}: {canonical_id} is its own ancestor")
            depth += 1
            if depth > len(entries):
                raise EvidenceError(f"{path}: parent cycle reached from {canonical_id}")
            walker = entries[walker].get("parent")

    index = AliasIndex({cid: entry["aliases"] for cid, entry in entries.items()})
    return Taxonomy(entries, index, path)


# ---------------------------------------------------------------------------
# Policy and lexicon
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Policy:
    raw: Mapping[str, Any]
    path: Path | None = None

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def list_of(self, key: str) -> tuple[str, ...]:
        return tuple(self.raw[key])

    @property
    def retry_limits(self) -> Mapping[str, int]:
        return self.raw["retry_limits"]


def load_policy(path: Path) -> Policy:
    data = _read_json(path)
    _validate(data, "policy.schema.json", path)
    if data["number_coverage_min"] > data["number_coverage_target"]:
        raise EvidenceError(f"{path}: number_coverage_min exceeds number_coverage_target")
    return Policy(data, path)


def require_client_blocklist(policy: Policy) -> None:
    """Refuse to run with an empty client blocklist.

    G4's CLIENT_NAME check matches against a list. An empty list matches
    nothing, so the check passes every document and reports success, which is
    the one failure mode worse than a rejection: a gate that looks green while
    enforcing nothing.

    The gate itself cannot tell an empty list from a satisfied one, so the
    refusal lives here. A tailoring run calls this before trusting the check.
    Tests that do not exercise client names do not call it.
    """
    if not policy.list_of("client_blocklist"):
        raise EvidenceError(
            f"{policy.path}: client_blocklist is empty, so the CLIENT_NAME check would "
            f"pass every document while enforcing nothing. Yash fills this in by hand."
        )


def require_default_location(policy: Policy) -> None:
    """Refuse to run without a default location.

    Section 7 falls back to the default whenever the posting's location is not
    in the allowlist. An empty default would put an empty string on the CV, or
    worse, invite a guess.
    """
    if not str(policy["default_location"]).strip():
        raise EvidenceError(
            f"{policy.path}: default_location is empty. It is the fallback whenever a "
            f"posting's location is not in location_allowlist, and it must never be guessed."
        )


@dataclass(frozen=True)
class Lexicon:
    """English word data. Not policy and not evidence."""

    wordlist: frozenset[str]
    irregular_past: frozenset[str]
    non_verb_ed: frozenset[str]
    spelling_variants: Mapping[str, str]

    def spell(self, token: str) -> str:
        return normalise_spelling(token, self.spelling_variants)


_ED_RE = re.compile(r"^[a-z][a-z]*ed$")


def load_lexicon(vocab_dir: Path) -> Lexicon:
    wordlist_path = vocab_dir / "wordlist_en.txt"
    try:
        lines = wordlist_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise EvidenceError(
            f"missing {wordlist_path}. Regenerate with python tools/build_wordlist.py"
        ) from None
    words = frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))

    verbs = _read_json(vocab_dir / "verbs_irregular_past.json")
    variants = _read_json(vocab_dir / "spelling_variants.json")
    return Lexicon(
        wordlist=words,
        irregular_past=frozenset(verbs["forms"]),
        non_verb_ed=frozenset(verbs["non_verb_ed"]),
        spelling_variants=dict(variants["variants"]),
    )


# ---------------------------------------------------------------------------
# The corpus and the loaded bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Corpus:
    """The evidence corpus, as defined in the spec.

    Ledger entries plus taxonomy aliases of confirmed ids, all fact text in
    experience.json, and the targets in synonyms.json.

    `synonym_permitted` is kept separate rather than folded in. A synonyms entry
    exists precisely so an employer's wording may appear when the literal term
    is absent from the evidence, and keeping it separate means that widening
    shows up in one named place instead of quietly enlarging what every other
    gate treats as evidenced.
    """

    tokens: frozenset[str]
    phrases: frozenset[tuple[str, ...]]
    synonym_permitted: frozenset[tuple[str, ...]]

    def contains(self, term_tokens: tuple[str, ...]) -> bool:
        if not term_tokens:
            return False
        if len(term_tokens) == 1:
            return term_tokens[0] in self.tokens
        return term_tokens in self.phrases

    def permitted(self, term_tokens: tuple[str, ...]) -> bool:
        return self.contains(term_tokens) or term_tokens in self.synonym_permitted


def _phrases(texts: Iterable[str]) -> tuple[frozenset[str], frozenset[tuple[str, ...]]]:
    tokens: set[str] = set()
    phrases: set[tuple[str, ...]] = set()
    for text in texts:
        seq = token_texts(text)
        tokens.update(seq)
        for size in range(2, _MAX_CORPUS_PHRASE + 1):
            for i in range(0, max(0, len(seq) - size + 1)):
                phrases.add(tuple(seq[i : i + size]))
    return frozenset(tokens), frozenset(phrases)


def build_corpus(ledger: Ledger, experience: Experience, synonyms: Synonyms, taxonomy: Taxonomy) -> Corpus:
    texts: list[str] = []
    for canonical_id in ledger.confirmed_ids:
        texts.append(canonical_id.replace("_", " "))
        if canonical_id in taxonomy.entries:
            texts.extend(taxonomy.aliases(canonical_id))
        entry = ledger.get(canonical_id)
        if entry:
            texts.extend(entry.services)
    for role in experience.roles:
        texts.extend(f.text for f in role.facts)
    texts.extend(synonyms.evidence_terms)

    tokens, phrases = _phrases(texts)
    synonym_permitted = frozenset(token_texts(t) for t in synonyms.jd_terms if token_texts(t))
    return Corpus(tokens, phrases, synonym_permitted)


@dataclass(frozen=True)
class Bundle:
    """Everything the gates read, loaded once and never mutated."""

    ledger: Ledger
    experience: Experience
    synonyms: Synonyms
    taxonomy: Taxonomy
    policy: Policy
    lexicon: Lexicon
    corpus: Corpus
    hashes: Mapping[str, str] = field(default_factory=dict)

    @property
    def evidence_hash(self) -> str:
        """One hash over the evidence files, for the run report."""
        joined = "|".join(f"{name}:{digest}" for name, digest in sorted(self.hashes.items()))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def load_bundle(
    root: Path | str = ROOT,
    *,
    evidence_dir: Path | str | None = None,
    vocab_dir: Path | str | None = None,
    config_dir: Path | str | None = None,
) -> Bundle:
    """Load and cross-validate every input file. Read-only throughout."""
    root = Path(root)
    evidence_dir = Path(evidence_dir) if evidence_dir else root / "evidence"
    vocab_dir = Path(vocab_dir) if vocab_dir else root / "vocab"
    config_dir = Path(config_dir) if config_dir else root / "config"

    taxonomy = load_taxonomy(vocab_dir / "taxonomy.json")
    ledger = load_ledger(evidence_dir / "ledger.json", known_ids=taxonomy.canonical_ids)
    experience = load_experience(evidence_dir / "experience.json")
    synonyms = load_synonyms(evidence_dir / "synonyms.json")
    policy = load_policy(config_dir / "policy.json")
    lexicon = load_lexicon(vocab_dir)

    role_ids = set(experience.role_ids)
    for canonical_id in ledger.confirmed_ids:
        entry = ledger.get(canonical_id)
        assert entry is not None
        unknown = sorted(set(entry.contexts) - role_ids)
        if unknown:
            raise EvidenceError(
                f"{ledger.path}: {canonical_id} lists contexts that are not role ids "
                f"in experience.json: {', '.join(unknown)}"
            )

    corpus = build_corpus(ledger, experience, synonyms, taxonomy)

    hashes = {
        "ledger.json": _sha256(evidence_dir / "ledger.json"),
        "experience.json": _sha256(evidence_dir / "experience.json"),
        "synonyms.json": _sha256(evidence_dir / "synonyms.json"),
        "taxonomy.json": _sha256(vocab_dir / "taxonomy.json"),
        "policy.json": _sha256(config_dir / "policy.json"),
    }
    return Bundle(ledger, experience, synonyms, taxonomy, policy, lexicon, corpus, hashes)
