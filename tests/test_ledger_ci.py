"""Ledger CI: denied is terminal.

A denied entry records that a technology was claimed and the claim was false.
Letting it move to another state would let the original failure back in through
a later edit.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.cli.confirmed_aliases import render
from app.cli.ledger_ci import compare, main
from app.loaders import ROOT, load_ledger, load_taxonomy


def _ledger(**states) -> dict:
    return {
        "schema_version": 1,
        "technologies": {cid: {"state": state} for cid, state in states.items()},
    }


# ---------------------------------------------------------------------------
# The comparison itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("new_state", ["confirmed", "unconfirmed"])
def test_a_denied_entry_moving_to_any_other_state_fails(new_state):
    violations = compare(_ledger(java="denied"), _ledger(java=new_state))
    assert [v.canonical_id for v in violations] == ["java"]
    assert violations[0].now == new_state


def test_deleting_a_denied_entry_fails():
    """Removal is the same move with an extra step: an id absent from the
    ledger is merely unconfirmed, not denied."""
    violations = compare(_ledger(java="denied"), _ledger())
    assert [v.canonical_id for v in violations] == ["java"]
    assert violations[0].now == "(removed)"


def test_a_denied_entry_staying_denied_passes():
    assert compare(_ledger(java="denied"), _ledger(java="denied", kafka="confirmed")) == ()


def test_unconfirmed_may_become_confirmed():
    """Only denied is terminal. Verifying something is the point of the system."""
    assert compare(_ledger(terraform="unconfirmed"), _ledger(terraform="confirmed")) == ()


def test_confirmed_may_become_denied():
    """Finding out a claim was false must always be possible."""
    assert compare(_ledger(kafka="confirmed"), _ledger(kafka="denied")) == ()


def test_adding_a_new_denied_entry_passes():
    assert compare(_ledger(), _ledger(java="denied")) == ()


def test_every_moved_entry_is_reported_not_just_the_first():
    violations = compare(
        _ledger(java="denied", mcp="denied", rag="denied"),
        _ledger(java="confirmed", mcp="unconfirmed", rag="denied"),
    )
    assert sorted(v.canonical_id for v in violations) == ["java", "mcp"]


# ---------------------------------------------------------------------------
# The command, against a real git repository
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "ledger.json").write_text(
        json.dumps(_ledger(java="denied", kafka="confirmed"))
    )
    git("add", ".")
    git("commit", "-q", "-m", "base")
    return tmp_path


def test_the_command_passes_when_nothing_moved(repo, capsys):
    assert main(["--base", "HEAD", "--repo", str(repo)]) == 0


def test_the_command_fails_when_a_denied_entry_moved(repo, capsys):
    (repo / "evidence" / "ledger.json").write_text(
        json.dumps(_ledger(java="confirmed", kafka="confirmed"))
    )
    assert main(["--base", "HEAD", "--repo", str(repo)]) == 1
    assert "java: denied -> confirmed" in capsys.readouterr().err


def test_a_repository_with_no_commits_fails_rather_than_passing(tmp_path):
    """HEAD names no commit in an empty repository.

    This asserted a pass before, which was the fail-open: the tool could not
    distinguish an unresolvable base from an empty diff, so it reported success
    having compared nothing. CI now always hands it a resolved merge-base sha,
    so this case cannot arise there, and where it does arise the honest answer
    is a refusal.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "ledger.json").write_text(json.dumps(_ledger(java="denied")))
    assert main(["--base", "HEAD", "--repo", str(tmp_path)]) == 2


def test_a_directory_that_is_not_a_repository_fails(tmp_path):
    assert main(["--base", "HEAD", "--repo", str(tmp_path)]) == 2


def test_a_valid_base_with_no_ledger_on_either_side_passes(repo):
    """The genuine nothing-to-compare case: the base resolves, and neither side
    carries the file. Distinct from an unresolvable base, which is a refusal."""
    assert main(["--base", "HEAD", "--repo", str(repo), "--path", "evidence/absent.json"]) == 0


# ---------------------------------------------------------------------------
# The review file
# ---------------------------------------------------------------------------


def test_the_review_file_lists_only_confirmed_ids(bundle):
    taxonomy = load_taxonomy(ROOT / "vocab" / "taxonomy.json")
    markdown = render(bundle.ledger, taxonomy)

    assert "Apache Kafka" in markdown
    assert "`kafka`" in markdown
    assert "producer side only" in markdown

    assert "Semantic Kernel" not in markdown
    assert "Terraform" not in markdown


def test_the_review_file_names_the_platform_services(bundle):
    taxonomy = load_taxonomy(ROOT / "vocab" / "taxonomy.json")
    markdown = render(bundle.ledger, taxonomy)
    assert "`Lambda`" in markdown
    assert "`DynamoDB`" in markdown


def test_the_review_file_is_honest_about_an_empty_ledger():
    from app.loaders import Ledger

    taxonomy = load_taxonomy(ROOT / "vocab" / "taxonomy.json")
    markdown = render(Ledger({}), taxonomy)
    assert "no alias can reach output" in markdown


def test_deleting_the_whole_ledger_fails(repo, capsys):
    """Deleting the file deletes every denied entry in it.

    Reading the head file's existence before the base version made this pass:
    the run took an early exit and reported nothing to check, which is the one
    outcome worse than a rejection.
    """
    (repo / "evidence" / "ledger.json").unlink()
    assert main(["--base", "HEAD", "--repo", str(repo)]) == 1
    assert "java: denied -> (removed)" in capsys.readouterr().err


def test_a_base_that_never_had_the_file_still_passes(repo):
    """A first commit adding the ledger has no base version to compare."""
    assert main(["--base", "HEAD", "--repo", str(repo), "--path", "evidence/nothing.json"]) == 0


def test_the_base_may_be_a_merge_base_sha_not_only_a_branch_name(repo):
    """CI resolves the base to a commit, so the tool must take one."""
    import subprocess

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "evidence" / "ledger.json").write_text(
        json.dumps(_ledger(java="unconfirmed", kafka="confirmed"))
    )
    assert main(["--base", sha, "--repo", str(repo)]) == 1


def test_an_unresolvable_base_fails_rather_than_reporting_nothing_to_check(repo, capsys):
    """A typo in the base ref must not read as an empty diff.

    Before this, a bad ref was indistinguishable from a base that predates the
    ledger: both printed nothing to check and exited 0. A check that cannot
    tell those apart reports success having compared nothing.
    """
    assert main(["--base", "no-such-ref", "--repo", str(repo)]) == 2
    assert "does not name a commit" in capsys.readouterr().err


def test_an_empty_base_argument_fails(repo):
    assert main(["--base", "", "--repo", str(repo)]) == 2
