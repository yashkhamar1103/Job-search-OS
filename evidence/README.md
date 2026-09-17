# evidence/

Three files live here and nothing else:

- `ledger.json`: technologies, their state, depth, contexts, and services
- `experience.json`: roles, facts, and metrics
- `synonyms.json`: approved vocabulary translations

The taxonomy is **not** an evidence file and lives in `vocab/taxonomy.json`. It
holds no claim about what anyone did, only what each term is called. Policy is
**not** an evidence file either and lives in `config/policy.json`.

## Rules

**Yash writes these files.** By hand, in git, outside any tailoring run. The
`.example.json` files next to them are templates with obviously fake data
(`faketech`, `fakerole`), so an example accidentally left in place fails the
loader rather than quietly becoming a claim.

**Nothing in the app writes here.** No endpoint, no UI, no code path. At runtime
on Azure the app directory is deployed read-only through run-from-package, so
this is enforced by the filesystem as well as by the code.

**`denied` is terminal.** CI fails any commit that moves a `denied` entry to
another state. See `app/cli/ledger_ci.py`.

**A metric is measured or recalled.** There is no `estimated`. An estimated
number is not evidence and cannot enter `experience.json`. A `recalled` metric
caps its bullet at Thin in Step 4.

## The three states

| State | Appears in output | Suggested as a gap to verify |
|---|---|---|
| `confirmed` | Yes, subject to depth, contexts, and services | n/a |
| `unconfirmed` | Never | Yes, Step 1 may name it |
| `denied` | Never | Never, and never as something to add |

A canonical id **absent** from the ledger is treated as unconfirmed for gating,
so it never appears in output. It is **not** suggestable: only an entry the
ledger explicitly marks `unconfirmed` can be surfaced as a gap. Absence from the
ledger is not an invitation, and the app never hands back a shopping list of
technologies to go and acquire.
