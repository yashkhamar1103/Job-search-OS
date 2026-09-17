# Resume Tailoring System

Takes a job description and produces an ATS-ready CV in PDF and DOCX.

The goal is not automation. The goal is to make fabrication structurally
impossible. `CLAUDE.md` is the spec and it is authoritative.

**Milestone 1 is complete: schemas, normalisation, G1 to G4, fixtures, tests.**
No LLM, no web, no Azure.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q
```

## What is here

| Path | What it holds |
|---|---|
| `evidence/` | `ledger.json`, `experience.json`, `synonyms.json`. Written by Yash, by hand, in git. Read-only at runtime. |
| `vocab/` | The technology taxonomy, an English wordlist, verb and spelling data. Reference data, not claims. |
| `config/policy.json` | Verbs, banned phrases, blocklists, thresholds, retry limits. |
| `app/gates/` | G1 to G4. Pure functions. No model call, no network. |
| `app/layout.py` | Page geometry and paragraph styles. The single source of truth for both the length gate and the milestone 3 renderer. |
| `app/cli/` | Developer and CI tools. Never part of a run. |
| `review/` | Generated files for Yash to read. |
| `tests/` | 452 tests. |

## The gates

| Gate | Checks |
|---|---|
| G1 technology | Taxonomy state, the job description watch list, unknown terms, ambiguous acronyms |
| G2 scope | Depth, context, platform services, exposure, cohabitation |
| G3 numbers | Citations, numeric expressions against cited metrics, versions, vague intensity, computed values |
| G4 structure | Bullet count, banned phrases, opening verbs, dashes, client names, copied text, rendered length, skills rules |
| G5 round trip | Milestone 3. Codes are registered already. |

Every finding carries a machine-readable code, the offending text span measured
against the original untouched string, a severity, a retry bucket, and what
happens when that budget is spent.

The truth and style split is the important one. A truth finding drops the bullet
after its retries. A style finding renders the bullet and flags it. **A style
rule never drops a factually clean bullet.**

## Before the first real run

Two values in `config/policy.json` ship empty because they are Yash's to supply,
and a run refuses to start without them rather than passing a check that
enforces nothing:

- `client_blocklist`. An empty list makes `CLIENT_NAME` match every document and
  report success.
- `default_location`. The fallback whenever a posting's location is not in the
  allowlist. It must never be guessed.

`evidence/` needs its three real files. The `.example.json` templates use
obviously fake ids (`faketech`, `fakerole`), so a template left in place fails
the loader rather than quietly becoming a claim.

## Commands

```bash
python -m pytest -q                        # the suite
python -m app.cli.ledger_ci --base origin/main   # denied is terminal
python -m app.cli.confirmed_aliases        # regenerate review/confirmed_aliases.md
python tools/build_wordlist.py             # regenerate vocab/wordlist_en.txt
```

## The incident this exists to prevent

Six technology claims were added to a CV after one confirmatory sentence under
pressure: Azure OpenAI Service, Semantic Kernel, Azure AI Foundry, Azure AI
Search, MCP, and RAG at code level. All six were false.

`tests/test_end_to_end.py` replays it. A job description asks for all six, the
CV claims all six, and every one is rejected by canonical id across bullets, the
summary, and the skills section, including old product names, lowercase,
hyphenated, and plural forms. The same file asserts that a truthful CV against
the same posting passes, because a gate that rejects everything is not a gate.
