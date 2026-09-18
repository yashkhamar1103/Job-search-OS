"""Repository-level rules from CLAUDE.md, enforced rather than remembered."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.errors import CODES
from app.loaders import ROOT

#: Built from code points, so this file does not trip the rule it enforces.
BANNED_DASHES = re.compile("[" + chr(0x2014) + chr(0x2015) + "]")

SOURCE_GLOBS = ("*.py", "*.json", "*.md", "*.yml", "*.yaml", "*.txt")

#: Dot directories are skipped wholesale rather than named one by one. A
#: virtualenv is not always called .venv, and a scan that walked one would be
#: checking third-party source for this project's house style. .github is the
#: one dot directory whose contents are ours.
KEEP_DOT_DIRS = {".github"}
SKIP_DIRS = {"__pycache__", "node_modules", "site-packages", "build", "dist"}

#: The generated wordlist is data, and the rule is about text this project
#: writes. It contains no dashes anyway; excluding it keeps the check fast.
SKIP_FILES = {"wordlist_en.txt"}


def _skipped(path: Path) -> bool:
    for part in path.relative_to(ROOT).parts[:-1]:
        if part in SKIP_DIRS:
            return True
        if part.startswith(".") and part not in KEEP_DOT_DIRS:
            return True
    return path.name in SKIP_FILES


def _sources() -> list[Path]:
    out: list[Path] = []
    for pattern in SOURCE_GLOBS:
        for path in ROOT.rglob(pattern):
            if not _skipped(path):
                out.append(path)
    return sorted(out)


def test_no_em_dash_anywhere():
    """Code comments, prompts, templates, docs, and output alike.

    The rule is easy to keep by hand and easy to forget once, which is exactly
    the kind of rule worth spending a test on.
    """
    offenders = []
    for path in _sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if BANNED_DASHES.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert not offenders, "em dash or horizontal bar found in: " + ", ".join(offenders)


def test_evidence_holds_only_the_three_files():
    """Vocabulary and policy are not evidence and must not drift back in."""
    present = {
        p.name
        for p in (ROOT / "evidence").iterdir()
        if p.is_file() and p.suffix == ".json" and not p.name.endswith(".example.json")
    }
    assert present <= {"ledger.json", "experience.json", "synonyms.json"}, (
        f"unexpected files in evidence/: {sorted(present)}"
    )
    assert (ROOT / "vocab" / "taxonomy.json").exists()
    assert (ROOT / "config" / "policy.json").exists()
    assert not (ROOT / "evidence" / "taxonomy.json").exists()
    assert not (ROOT / "evidence" / "config.json").exists()


def test_every_example_file_is_obviously_fake():
    for path in (ROOT / "evidence").glob("*.example.json"):
        text = path.read_text(encoding="utf-8").lower()
        assert "fake" in text, f"{path.name} does not look obviously fake"
        assert "template, not evidence" in text


def test_every_registered_code_has_a_description_and_a_bucket():
    for code, spec in CODES.items():
        assert spec.description.strip(), code
        assert spec.gate
        assert spec.bucket
        assert spec.exhaustion


def test_no_gate_module_shells_out_or_reaches_the_network():
    """A gate reads only its inputs and the loaded evidence."""
    import inspect

    from app.gates import GATES
    from app.gates import context as gate_context
    from app import computed, jd, layout, normalise, numbers

    for module in (*GATES, gate_context, computed, jd, layout, normalise, numbers):
        source = inspect.getsource(module)
        for forbidden in ("subprocess", "socket", "requests", "httpx", "urllib", "anthropic"):
            assert forbidden not in source, f"{module.__name__} references {forbidden}"


def test_shelling_out_is_confined_to_the_cli_tools():
    """git is a developer and CI concern. It must not be reachable from a run."""
    from app.cli import ledger_ci

    assert "subprocess" in Path(ledger_ci.__file__).read_text(encoding="utf-8")
    for path in (ROOT / "app").glob("*.py"):
        assert "subprocess" not in path.read_text(encoding="utf-8"), path.name


def test_policy_ships_its_personal_fields_empty():
    """client_blocklist and default_location are Yash's to supply, and a run
    refuses to start without them rather than enforcing nothing."""
    policy = json.loads((ROOT / "config" / "policy.json").read_text(encoding="utf-8"))
    assert policy["client_blocklist"] == []
    assert policy["default_location"] == ""
    assert policy["model_id"] is None


@pytest.mark.parametrize("path", ["vocab/taxonomy.json", "config/policy.json"])
def test_shipped_data_files_parse(path):
    json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_the_source_scan_does_not_walk_a_virtualenv(tmp_path, monkeypatch):
    """A virtualenv is not always called .venv.

    The first fresh-clone run of this suite used one called .v, and the em dash
    scan happily reported findings in third-party site-packages.
    """
    scanned = {p.relative_to(ROOT).as_posix() for p in _sources()}
    assert not any("site-packages" in name for name in scanned)
    assert not any(
        part.startswith(".") and part not in KEEP_DOT_DIRS
        for name in scanned
        for part in name.split("/")[:-1]
    )
    assert ".github/workflows/ci.yml" in scanned, "the workflow is ours and must be scanned"


# ---------------------------------------------------------------------------
# The CI workflow
# ---------------------------------------------------------------------------

WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_checkout_is_not_shallow():
    """The ledger check needs the merge base, which a shallow clone lacks."""
    assert "fetch-depth: 0" in _workflow_text()


def test_the_workflow_runs_on_pull_requests_as_well_as_pushes():
    text = _workflow_text()
    head = text.split("jobs:", 1)[0]
    assert "pull_request:" in head
    assert "push:" in head


def test_the_ledger_check_takes_a_resolved_commit_not_a_branch_name():
    """A branch name is the wrong handle.

    The default branch is a setting that can point anywhere, including at the
    branch under test, in which case the check compares that branch against
    itself and passes while comparing nothing.
    """
    text = _workflow_text()
    ledger_step = text.split("name: Ledger CI", 1)[1].split("- name:", 1)[0]
    assert "steps.base.outputs.sha" in ledger_step
    assert "default_branch" not in ledger_step
    assert "merge-base" in text


def test_the_base_resolution_prefers_the_pull_requests_own_base_commit():
    text = _workflow_text()
    assert "github.event.pull_request.base.sha" in text


def test_a_failed_fetch_fails_the_job_rather_than_passing_quietly():
    """`|| true` on the base fetch leaves the check with nothing to compare
    against and a green tick, which is worse than a rejection."""
    text = _workflow_text()
    for line in text.splitlines():
        if "git fetch" in line:
            assert "|| true" not in line, f"fetch swallows failure: {line.strip()}"


def test_the_review_file_check_sees_a_newly_generated_file():
    """git diff does not report untracked files, so a first generation would
    read as no change and land uncommitted."""
    text = _workflow_text()
    review_step = text.split("name: Review file is current", 1)[1]
    assert "--intent-to-add" in review_step


def test_the_red_team_fixture_is_pure_ascii_on_disk():
    """The fixture carries an em dash, a zero width space and a Cyrillic a as
    test data. All three are delivered as \\u escapes.

    Re-serialising it with ensure_ascii=False writes them as literal characters,
    which is legal JSON and tripped the em dash rule from an unrelated file.
    This asserts the encoding directly, so the next re-serialisation fails here
    with the reason rather than somewhere else with a symptom.
    """
    path = ROOT / "tests" / "redteam" / "redteam_fixture.json"
    raw = path.read_bytes()
    offenders = [
        (i, hex(byte)) for i, byte in enumerate(raw) if byte > 0x7F
    ]
    assert not offenders, (
        f"{path.name} contains {len(offenders)} non-ASCII bytes, first at offset "
        f"{offenders[0][0]}. Re-serialise with json.dump(..., ensure_ascii=True)."
    )


def test_the_fixture_still_carries_its_escaped_adversarial_characters():
    """The lock must not be satisfiable by deleting the test data it protects."""
    import json

    path = ROOT / "tests" / "redteam" / "redteam_fixture.json"
    source = path.read_text(encoding="utf-8")
    for escape in ("\\u2014", "\\u200b", "\\u0430"):
        assert escape in source, f"{escape} is missing from the fixture"

    loaded = json.loads(source)
    texts = " ".join(c.get("text", "") for c in loaded["cases"])
    assert chr(0x2014) in texts and chr(0x200B) in texts and chr(0x0430) in texts
