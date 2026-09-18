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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail if a denied ledger entry changed state.")
    parser.add_argument("--base", default="origin/main", help="git ref to compare against")
    parser.add_argument("--path", default=DEFAULT_PATH, help="path to the ledger inside the repo")
    parser.add_argument("--repo", default=".", help="repository root")
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

    base = _git_show(base_commit, args.path, repo)

    if base is None:
        if head_path.exists():
            print(f"{args.path} is not present at {args.base}. Treating as a new file.")
        else:
            print(f"{args.path} exists at neither {args.base} nor HEAD. Nothing to check.")
        return 0

    if head_path.exists():
        head = json.loads(head_path.read_text(encoding="utf-8"))
    else:
        print(f"{args.path} was deleted. Every entry it held is compared as removed.")
        head = {"technologies": {}}

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
