"""Print the bucket table as a review artefact.

The table is read by a person deciding whether a code is classified correctly,
so it prints the resolved retry budget rather than the raw override. A structure
finding is not a per-block retry at all, so its budget prints as n/a: a zero
there reads as "retried zero times", which is a different claim from "retries do
not apply to this code".

    python tools/bucket_table.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.errors import CODES  # noqa: E402
from app.gates.buckets import STRUCTURE, TABLE, retries_for  # noqa: E402
from app.loaders import ROOT, load_policy  # noqa: E402


def rows() -> list[tuple[str, str, str, str, str, str]]:
    limits = load_policy(ROOT / "config" / "policy.json").retry_limits
    out = []
    for code, (bucket, severity, override) in TABLE.items():
        spec = CODES[code]
        if bucket == STRUCTURE:
            budget = "n/a"
        else:
            budget = str(retries_for(code, limits))
            if override is not None:
                budget += " (override)"
        out.append((code, spec.gate.value, bucket, severity, budget, spec.exhaustion.value))
    return out


def main() -> int:
    table = rows()
    widths = [max(len(row[i]) for row in table) for i in range(6)]
    headers = ("CODE", "GATE", "BUCKET", "SEVERITY", "RETRIES", "EXHAUSTION")
    widths = [max(w, len(h)) for w, h in zip(widths, headers)]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for row in table:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
