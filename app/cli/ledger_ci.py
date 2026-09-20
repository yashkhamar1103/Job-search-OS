"""Ledger CI: denied is terminal.

A `denied` entry records that a technology was claimed and the claim was false.
Letting it move to another state would let the original failure back in through
a later edit, so CI fails any diff that does.

Removing a denied entry is the same move with an extra step, because an id
absent from the ledger is merely unconfirmed rather than denied. Removal fails
too.

Reads two versions of the file and compares. Shells out to git only to fetch the
base version, which is a developer and CI concern, never a tailoring run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DENIED = "denied"
DEFAULT_PATH = "evidence/ledger.json"


@dataclass(frozen=True)
class Violation:
    canonical_id: str
    was: str
    now: str

    def __str__(self) -> str:
        return f"  {self.canonical_id}: {self.was} -> {self.now}"


def _states(payload: dict) -> dict[str, str]:
    return {cid: entry["state"] for cid, entry in payload.get("technologies", {}).items()}


def compare(base: dict, head: dict) -> tuple[Violation, ...]:
    """Every denied entry in `base` that is not still denied in `head`."""
    before, after = _states(base), _states(head)
    out = [
        Violation(cid, DENIED, after.get(cid, "(removed)"))
        for cid, state in sorted(before.items())
        if state == DENIED and after.get(cid) != DENIED
    ]
    return tuple(out)


class UnresolvableBase(Exception):
    """The base ref does not name a commit in this repository."""


class PolicyMissing(Exception):
    """The policy file is not where it was expected."""


def _resolve_commit(ref: str, repo: Path) -> str:
    """Resolve `ref` to a commit, or raise.

    Separated from reading the file on purpose. Without it, a base ref with a
    typo in it is indistinguishable from a base commit that simply predates the
    ledger, and both read as nothing to check. A check that cannot tell those
    apart reports success when it has compared nothing, which is the failure
    mode this whole tool exists to prevent.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise UnresolvableBase(ref)
    return result.stdout.strip()


def _git_show(ref: str, path: str, repo: Path) -> dict | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def _check_permanent_denials(
    repo: Path, policy_rel: str, head_path: Path, head: dict
) -> tuple[str, ...]:
    """Every permanently denied id, checked against the head ledger.

    Reads the policy file directly rather than importing the app, so the CI
    tool stays a thin git-and-JSON utility. The comparison itself is the one in
    app.loaders, imported so that CI and the loader cannot drift apart on what
    counts as satisfied.
    """
    from app.loaders import permanent_denial_failures

    policy_path = repo / policy_rel
    if not policy_path.exists():
        raise PolicyMissing(str(policy_path))

    required = json.loads(policy_path.read_text(encoding="utf-8")).get(
        "permanently_denied_ids", []
    )
    if not required:
        return ()

    if not head_path.exists():
        return tuple(f"{cid}: evidence/ledger.json does not exist" for cid in required)

    states = {cid: entry.get("state") for cid, entry in head.get("technologies", {}).items()}
    return permanent_denial_failures(states, required)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail if a denied ledger entry changed state.")
    parser.add_argument("--base", default="origin/main", help="git ref to compare against")
    parser.add_argument("--path", default=DEFAULT_PATH, help="path to the ledger inside the repo")
    parser.add_argument("--repo", default=".", help="repository root")
    parser.add_argument(
        "--policy",
        default="config/policy.json",
        help="path to the policy file, inside the repo",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    head_path = repo / args.path

    # The base is read first, on purpose.
    #
    # Checking the head file's existence first looks harmless and is not: a
    # commit that deletes the whole ledger would take that early exit and pass,
    # even though deleting the file deletes every denied entry in it. Deletion
    # is the case the check exists for, so the head's absence has to be read as
    # an empty ledger and compared, not as nothing to do.
    try:
        base_commit = _resolve_commit(args.base, repo)
    except UnresolvableBase:
        print(
            f"base {args.base!r} does not name a commit in {repo}.\n"
            f"Refusing to report success without comparing anything.",
            file=sys.stderr,
        )
        return 2

    head = (
        json.loads(head_path.read_text(encoding="utf-8"))
        if head_path.exists()
        else {"technologies": {}}
    )

    # Runs before any early return, on purpose.
    #
    # The transition check compares two states and can only see one that
    # changed. It cannot see a state that was never written down: a ledger that
    # was never committed reads as empty at both base and head, finds no
    # transitions, and passes forever. That is the whole window before Yash
    # writes the file, which is exactly when the six claims are unguarded.
    try:
        permanent = _check_permanent_denials(repo, args.policy, head_path, head)
    except PolicyMissing as missing:
        print(
            f"policy file not found: {missing}.\n"
            f"Refusing to report success without checking the permanent denials.",
            file=sys.stderr,
        )
        return 2

    if permanent:
        print("permanently denied ids are not recorded as denied at HEAD:", file=sys.stderr)
        for failure in permanent:
            print(f"  {failure}", file=sys.stderr)
        print(
            "\nThe transition check sees a state that changed. It cannot see a state "
            "that was never written, so this list is what guards a ledger that does "
            "not exist yet.",
            file=sys.stderr,
        )
        return 1

    base = _git_show(base_commit, args.path, repo)

    if base is None:
        if head_path.exists():
            print(f"{args.path} is not present at {args.base}. Treating as a new file.")
        else:
            print(f"{args.path} exists at neither {args.base} nor HEAD. Nothing to check.")
        return 0

    if not head_path.exists():
        print(f"{args.path} was deleted. Every entry it held is compared as removed.")

    violations = compare(base, head)
    if not violations:
        print(f"denied entries unchanged between {args.base} and the working tree")
        return 0

    print("denied is terminal. These entries moved:", file=sys.stderr)
    for violation in violations:
        print(str(violation), file=sys.stderr)
    print(
        "\nA denied entry records a claim that was made and was false. "
        "It does not get to be reconsidered.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
