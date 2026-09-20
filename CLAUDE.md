# CLAUDE.md: Resume Tailoring System

Read this whole file before writing any code. It is the spec and it is authoritative. Where it is silent, ask. Do not guess.

## 1. Purpose

A system that takes a job description (JD) and produces an ATS-ready CV in PDF and DOCX. It runs in a laptop browser and as an iPhone home-screen web app.

The goal is not automation. The goal is to make fabrication structurally impossible.

Background: during an earlier engagement, six technology claims were added to a CV after one confirmatory sentence under pressure:
- Azure OpenAI Service
- Semantic Kernel
- Azure AI Foundry
- Azure AI Search
- MCP
- RAG at code level

All six were false. They were caught later and removed. This system exists so that cannot happen again, whether the pressure comes from the model or from the user.

## 2. Non-negotiable architecture rules

1. **Gates are deterministic code.** Every constraint in Section 5 is enforced by pure Python functions in `app/gates/`. A gate reads only its inputs and the loaded evidence files. It never calls an LLM and never makes a network request. Prompts may repeat the rules as guidance, but the gate is the only authority.
2. **Nothing grades its own output.** The model generates, code validates, and the user confirms. The model never decides whether its own output passes.
3. **Evidence files are read-only at runtime.** No endpoint, UI, or code path in the app writes to `evidence/`. Evidence changes are made by hand, in git, outside any tailoring run.
4. **Fail closed.** If a gate cannot classify something, the item is rejected or held for review, never accepted by default. This covers unknown terms, unparseable model output, and missing metrics.
5. **Structured model output only.** Every model call returns JSON through tool use with a strict input schema. Free-text model output is never regex-parsed into a CV.

## 3. Rules for you (Claude Code)

- **Evidence files:** `evidence/` holds `ledger.json`, `experience.json`, and `synonyms.json`, and nothing else. Do not create or edit real entries in any of them.
  - Create `evidence/*.example.json` with obviously fake data (for example `"faketech"`) and schema validation.
  - Yash writes the real files.
- **Vocabulary and policy are not evidence.** `vocab/taxonomy.json` holds no claim about what anyone did, only what each term is called, and `config/policy.json` holds verbs, blocklists, and thresholds. You may write both. The generated `review/confirmed_aliases.md` is what Yash reviews.
- **Gate implementation:** do not implement any gate as a prompt instruction, an LLM call, or an "ask the model to double-check" step.
- **Gate strictness:** do not relax a gate to make a test pass or to make output look better. If a gate blocks output that looks correct, stop and report it.
- **Build order:** follow the milestones in Section 10. Finish and test each one before starting the next.
- **Open decisions:** ask before deciding anything listed in Section 11.
- **Em-dashes:** no em-dash character (U+2014) anywhere. This covers code comments, prompts, templates, docs, and output.

## 4. Evidence files (JD-blind, written only by Yash)

### 4.1 `evidence/ledger.json`: technologies

Each key must be a canonical id from `vocab/taxonomy.json`. Values in angle brackets are placeholders. Do not fill them.

```json
{
  "schema_version": 1,
  "technologies": {
    "kafka": {
      "state": "confirmed",
      "depth": "<built|used|exposure>",
      "contexts": ["amnex"],
      "scope_note": "producer side only",
      "versions": [],
      "evidence": "<what Yash personally did, where, and what proves it>",
      "added": "<YYYY-MM-DD>",
      "origin": "<unprompted|after_gap>"
    },
    "aws": {
      "state": "confirmed",
      "depth": "<built|used|exposure>",
      "contexts": ["amnex"],
      "scope_note": "Data Lake 3.0 only",
      "services": ["Lambda", "S3", "DynamoDB", "API Gateway", "CloudWatch"],
      "evidence": "<...>",
      "added": "<YYYY-MM-DD>",
      "origin": "<unprompted|after_gap>"
    },
    "terraform":       { "state": "unconfirmed" },
    "java":            { "state": "denied" },
    "semantic_kernel": { "state": "denied" }
  }
}
```

**States**
- `confirmed`: may appear in output, subject to the depth, contexts, and services checks.
- `unconfirmed`: never appears in output. Step 1 may name it as a gap Yash could verify outside the app.
- `denied`: never appears in output, and is never suggested as something to verify or add.
  - Step 1 may report it only as "required by JD, not held."
  - `denied` is terminal. CI fails any commit that moves a `denied` entry to another state, and fails a commit that deletes one, because an id absent from the ledger is merely unconfirmed.

**Absence is not a state.** A canonical id in the taxonomy that is not in the ledger is treated as `unconfirmed` for gating, so it never appears in output. It is **not** suggestable: only an entry the ledger explicitly marks `unconfirmed` may be surfaced as a gap to verify. The app never hands back a shopping list of technologies to go and acquire.

**Fields**
- `depth`: how deeply Yash worked with the technology.
  - `built`: designed it or wrote it.
  - `used`: configured, integrated, or operated it.
  - `exposure`: worked on a system that had it.
- `contexts`: role ids from `experience.json` where the technology may be mentioned. A confirmed technology under any other role is rejected.
- `services`: for platforms. Any sub-service a bullet names must be in this list. A confirmed platform with no `services` list enumerates nothing and therefore confirms no sub-service.
- `versions`: version strings a bullet may attach to this technology.
- `origin`: see Step 4. The app also derives origin independently from the gap log.

### 4.2 `evidence/experience.json`: roles, facts, metrics

```json
{
  "roles": [
    {
      "id": "amnex",
      "employer": "Amnex Infotechnologies",
      "title": "<exact title>",
      "start": "<YYYY-MM>",
      "end": "<YYYY-MM>",
      "location": "<...>",
      "facts": [
        { "id": "amnex-f1", "text": "<plain statement of what Yash did, in his words>" }
      ],
      "metrics": [
        {
          "id": "amnex-m1",
          "value": "<number with unit>",
          "what": "<what it measures>",
          "source": "<measured|recalled>",
          "note": "<how it was measured or where it is recorded>"
        }
      ]
    }
  ]
}
```

`source` has no `estimated` value. Estimated numbers are not evidence and cannot enter this file.

### 4.3 `vocab/taxonomy.json`: known technology vocabulary

This file maps every known technology term and alias to a canonical id, including technologies Yash does not have. It is deliberately much larger than the ledger.

It is **not** an evidence file and does not live in `evidence/`. It holds no claim about what anyone did, only what each term is called.

Include historical and current product names, because renames defeat naive matching. Examples:
- `azure_ai_search`: "Azure AI Search", "Azure Cognitive Search", "Cognitive Search"
- `azure_ai_foundry`: "Azure AI Foundry", "AI Foundry", "Azure AI Studio", "Microsoft Foundry"
- `azure_openai`: "Azure OpenAI Service", "Azure OpenAI", "AOAI"

Entries may carry a `parent`, naming the platform a sub-service belongs to. G2's services check needs it: without a parent link there is no way to know that Lambda is a sub-service of AWS.

`review/confirmed_aliases.md` is generated from this file and the ledger. It lists the alias sets of confirmed ids only, and it is the file Yash reviews. The taxonomy itself is reference data.

### 4.4 `evidence/synonyms.json`: approved vocabulary translations

This file resolves the tension between "use the employer's exact terminology" and "only claim what the evidence supports." Yash declares which employer terms describe his real work. Example: a JD term "RESTful microservices" maps to an evidence term.

Only entries in this file let a JD term appear in output when the literal term is absent from the evidence. The model cannot add entries.

An approved entry puts **both** sides within reach of the watch-list check: the evidence term joins the evidence corpus, and the JD term becomes permissible in output. It unlocks **wording only**. G1's taxonomy check runs independently, so a synonym containing an `unconfirmed` or `denied` canonical id is still rejected. Without that rule this file would be a fabrication backdoor.

### 4.5 `config/policy.json`

Not an evidence file and not under `evidence/`: none of it is a claim about what Yash has done. Holds:
- the client-name blocklist
- banned phrases
- the build-verb list, the weak-opener denylist, and the opening-verb coverage list
- ambiguous acronyms
- vague intensity words, vague quantifiers, proficiency qualifiers, and duration hedges
- the location allowlist and default location
- retry limits, split by bucket
- `cooling_off_hours`
- `fit_threshold`
- `max_pages`
- the model id and per-run token budget

Defaults are given in Sections 5 and 6.

Two values ship empty because they are Yash's to supply, and a run refuses to start without them rather than passing a check that enforces nothing: `client_blocklist` and `default_location`.

## 5. Gates (all in `app/gates/`, all pure functions)

Each gate returns either `pass` or a list of rejections. Each rejection carries a machine-readable code and the offending text span.

**Evidence corpus:** ledger entries plus taxonomy aliases of confirmed ids, the services of confirmed platforms, all fact text in `experience.json`, and the targets in `synonyms.json`.

**Text normalisation (shared by all gates)**
- Apply Unicode NFKC, casefold, and collapse whitespace.
- Decompose first, drop combining marks and format characters, then recompose. A precomposed and a decomposed accent must fold to the same token, and a zero width space or soft hyphen must not be able to hide a technology name.
- Keep `.`, `#`, `+`, and `/` inside tokens, so `.NET`, `C#`, `C++`, `Node.js`, and `CI/CD` survive.
- Every Unicode letter is a letter. A non-ASCII letter must never act as a separator: an ASCII-only token pattern silently truncated the token around it, and one Cyrillic `a` split `RAG` into `r` and `G`, making a denied technology invisible to every gate.
- Match aliases longest-first, on token boundaries. Every alias is indexed twice, spaced and with whitespace removed, so a zero width space that joins two words into one token still resolves.
- Handle plural and hyphenated variants. Plural tolerance applies from four characters up, so a short acronym cannot be widened into a different word.
- Fold `-ise` and `-ize` spellings together so one config entry covers both.

**Gate precedence.** One ordered claim over spans:

```
G0 hygiene  ->  G3 numeric and version spans  ->  client blocklist
            ->  taxonomy match  ->  proper-noun residue heuristic
```

A span claimed earlier is invisible to everything later. Longest match wins inside the blocklist, so "Northwind Retail" consumes "Northwind" and one name is named once. Findings are deduplicated by (code, span) before the run report.

Without an order the same characters get reported by three gates at once: a blocklisted client name is also a proper noun the taxonomy has never heard of, and a cited multiplier such as `3x` carries both a letter and a digit, which is exactly the shape the residue heuristic hunts for.

Alias spans are resolved before numeric spans even though the chain ranks numbers first, and that is not a contradiction. Digits inside a product name are part of the name rather than a claim about scale: `Route 53`, `OAuth 2.0` and `SOC 2` are names. Settling that question first is what makes the rest of the chain well defined.

**Block types.** G1, G2, G3, and G4 all run over bullets, the summary, and the skills section. Two checks are bullet-only because they have no meaning elsewhere: G2's context check, since neither the summary nor the skills section sits under a role, and G3's citation check, since neither carries citations.

### G0 Text hygiene gate (pre-gate)

Runs before every other gate. Truth bucket, **zero retries**, never auto-corrected. Silently repairing the text would produce clean output and erase the only evidence that something put the character there.

- **Invisible characters:** any zero-width, invisible, or bidi control character (U+200B to U+200F, U+2060, U+00AD, U+FEFF, bidi embeds, overrides and isolates) is rejected with `INVISIBLE_CHAR`.
- **Mixed script:** a token drawing characters from more than one Unicode script is rejected with `MIXED_SCRIPT`. This is how a homoglyph is smuggled into an otherwise Latin word.
- **Non-Latin letters:** a letter outside the Latin script is rejected with `NON_LATIN_SCRIPT`. Latin Extended accented characters stay legal.

**Asymmetric by design.** On generated text, reject. On job description ingest, do not reject: strip, record what was removed to the run report, and flag any term extracted from a stripped span. Yash does not control what a recruiter pasted into a posting, and refusing to read one over a stray soft hyphen would make the tool unusable for a reason that is nobody's fault.

The homoglyph fold in `app/normalise.py` runs **after** tokenisation, never instead of this gate. The fold exists so the term is still classified correctly, so a homoglyph attack reports both the script violation and the denial it was hiding.

### G1 Technology gate

- **Taxonomy check:** every taxonomy term found in a bullet, the summary, or the skills section must map to a `confirmed` ledger entry. Otherwise reject with `TECH_UNCONFIRMED` or `TECH_DENIED`.
- **JD watch list:** before Step 2, build a candidate-term set from the JD deterministically.
  - Include: taxonomy matches, CamelCase tokens, tokens mixing letters with `.#+/` or digits, and mid-sentence capitalised tokens not in an English wordlist.
  - A taxonomy match puts every alias of that canonical id on the list, not only the posting's spelling.
  - A token of digits alone is excluded. Otherwise every number becomes a watch term and G1 competes with G3 over the same digits.
  - A model call may also extract JD terms. Its output can only add to the watch list, never remove from it.
  - Unknown JD terms go into `review/taxonomy_candidates.json` for Yash, never into the ledger.
- **Watch-list check:** a watch-list term that appears in output but not in the evidence corpus is rejected with `JD_TERM_NOT_IN_EVIDENCE`. This is the primary defence, because the JD is where fabrications come from.
- **Unknown terms:** an output token that matches the unknown-proper-noun heuristic and is in neither the taxonomy nor the evidence corpus is held for user review with `UNKNOWN_TERM`. Held items are not rendered until approved.
- **Ambiguous acronyms:** acronyms listed in config (for example `MCP`, `SK`, `RAG`) are matched as whole tokens. Any hit on a non-confirmed id is rejected.

### G2 Scope gate

- **Depth:** a build verb (from the config list, default: built, designed, architected, implemented, developed, engineered, wrote, authored, created) in the same bullet as a technology whose `depth` is not `built` is rejected with `SCOPE_DEPTH`.
- **Context:** a technology under a role not in its `contexts` is rejected with `SCOPE_CONTEXT`. Bullets only.
- **Services:** a sub-service not in the platform's `services` list is rejected with `SCOPE_SERVICE`. G1 also rejects it as unconfirmed, on purpose: each gate stays independently correct rather than relying on the other having run.
- **Exposure:** a technology with `depth` `exposure` may not appear in bullet text at all (`SCOPE_EXPOSURE_IN_BULLET`), nor in the skills section (`SKILLS_EXPOSURE`). It may appear only on a separate environment line.
- **Cohabitation:** split the text into sentences deterministically. For each sentence, collect the matched canonical ids that have a non-empty `contexts` list. If the intersection of their contexts is empty, reject with `SCOPE_COHABITATION`. Inside a bullet, the intersection must also include the bullet's own role.
  - At least two participants are required. One technology cannot cohabit with anything, and without the guard a single technology under the wrong role reported both `SCOPE_CONTEXT` and `SCOPE_COHABITATION`, which is one finding named twice.
  - This is the check per-technology context cannot make. Two technologies can each be confirmed, each under a role of its own, and still describe work that never happened by sitting next to each other.
- **Known limit:** free-text scope such as "producer side only" cannot be enforced in code. `scope_note` is shown next to the bullet in Step 4 for human review.

### G3 Number gate

- **Citations:** every bullet must cite at least one `fact_id` and may cite `metric_ids`. A bullet citing none is rejected with `CITATION_MISSING`; an id absent from `experience.json` with `CITATION_UNKNOWN`.
- **Numbers:** extract every numeric expression from the bullet:
  - integers, decimals, and percentages
  - currency amounts
  - multipliers (`3x`) and magnitudes (`10K`, `2M`)
  - ranges
  - number words ("two" through "twenty", "dozens", "hundreds", "thousands", "millions")

  Each one, after normalisation, must equal a `value` in the bullet's cited metrics. Otherwise reject with `NUMBER_UNSUPPORTED`.
  - The kind is part of the identity: 40, 40%, and 40x are three different claims. A trailing plus is its own kind too, so a metric of 40% does not support a claim of 40% or more.
  - A magnitude is multiplied out, so `2.5M` and `2,500,000` are the same number.
- **Versions:** a number attached directly to a technology term (`.NET 8`, `Angular 16`) is a version. It is allowed only if listed in that entry's `versions`; otherwise `VERSION_UNSUPPORTED`. Only nothing or a single space may sit between the name and the number: anything else, a comma above all, means the number belongs to the next item in a list.
  - A number **inside** a matched alias is part of the product name and is not a claim about scale. `OAuth 2.0`, `Route 53`, and `SOC 2` are names.
- **Vague intensity words:** words such as "significantly", "dramatically", "substantially", and "massively" are rejected with `VAGUE_METRIC`, because they imply a number that does not exist.
- **Hedged numbers:** position is the rule, not presence. The same word hedges in one place and does not in another.
  - A `policy.leading_hedges` entry **preceding** a number, within two tokens, is `VAGUE_METRIC`. "roughly 40%" widens a measured value.
  - A `policy.trailing_hedges` entry **following** a numeric span is `VAGUE_METRIC`. "12+ services" and "40% or more" widen a number the metric records exactly.
  - Neither fires otherwise. "3x over the prior pipeline" compares; "over the weekend window" is a preposition with no number in sight. Checking presence rather than position blocked all three.
  - The computed years rendering `N+ years` is exempt from the **trailing** rule only, being code-generated from the role dates. A leading hedge on a computed value is still the model widening a number it was handed, so "over 6 years" is rejected.
  - **Bounds are measurements.** A hedged phrase is legal when it appears **verbatim** in the `value` of a metric the bullet cites. A p95 latency recorded as `under 200ms` is a measured value whose form contains the word "under", and rewriting it as "200ms" would state something the measurement does not support. The comparison is the metric's exact text, case and spacing aside: "under 250ms" is a different claim and stays rejected, and the same phrase in a block citing nothing has nothing to stand on. With the computed years form, this is the only hedge exemption.
- **Unquantified scale:** a `policy.vague_quantifiers` entry ("several", "numerous", "a handful of") modifying a countable noun, with no numeric span anywhere in the same clause, is rejected with `UNQUANTIFIED_SCALE`. It asserts a scale the evidence does not carry, and the retry fixes it by naming the number or dropping the word.
  - A countable noun after a quantifier is a plural one, so a plural test is the whole countable test. A mass noun ("various tooling") asserts no count and does not fire.
  - A preposition ends the quantifier's phrase. Without that boundary, "various tooling for order events" reaches past its own mass noun to a plural three tokens later and rejects a bullet claiming no scale at all.
  - A number in the same clause excuses the quantifier, because the claim then carries its own quantity. That also settles the overlap with the vague magnitude words: "dozens of records" parses as a numeric span, so this rule stays quiet and the number gate rejects it as unsupported, which is what gate precedence already says.
- **Form mismatch:** a value that matches a cited metric but not its form is `NUMBER_FORM_MISMATCH`, not `NUMBER_UNSUPPORTED`. Plain 3 against a multiplier of 3x, "three times" against "3x", "40 percent" against "40%". They are different defects: one means the model invented a number, the other means it has the right metric and rendered it wrong, and a retry told which form to use converges instead of guessing at a number it already has.
- **Summary and skills:** no citation exists, so every number and every vague intensity word is rejected with `SUMMARY_NUMBER_UNCITED`, together with every duration hedge ("nearly", "almost", "over", "more than", "half a decade", "a decade").
  - The one exception is the computed-values registry below.

#### Computed values

Numbers in the summary may come only from code-computed values, never from the model. The model cannot widen this registry.

`computed.total_years_experience`:
- union of role intervals from `experience.json`, overlaps counted once
- gaps excluded, education excluded
- `total_years = floor(union_months / 12)`, anchored to the run date
- allowed renderings: `N years` or `N+ years` where `N == total_years`. The singular is additionally allowed when `N` is one, because "one years" is not English.
- every other numeric form is rejected, including "nearly", "almost", "over", "more than", "half a decade", "a decade"
- `total_years` and the anchor date are printed in the run report. If they disagree with a figure used elsewhere, flag it rather than silently picking one.

### G4 Structure and style gate

- **Bullet count:** at most 3 bullets per role (`BULLET_COUNT`). Not a per-bullet retry: the step reselects.
- **Banned phrases:** case-insensitive and lemma-aware (`BANNED_VERB`): spearheaded, championed, drove alignment, leveraged synergies, owned the vision, delivered on.
- **Opening verb:** a **denylist**, not an allowlist check. A bullet is rejected with `WEAK_OPENING` when it opens with:
  - any phrase in `policy.weak_openers`, matched longest-first at position 0
  - a word ending in `-ing` or `-ly`
  - `was`, `were`, `have`, `had`, `has`
  - no verb in the first two tokens
- **Opening verb coverage:** an opening verb that clears the denylist but is absent from `policy.opening_verbs` reports `OPENING_VERB_UNLISTED`. It **never** rejects, and the finding carries the exact config line to add it. Enforcing the list would let a style rule drop a truthful bullet over a verb nobody happened to think of.
- **Dashes:** no U+2014, U+2015, or `--` anywhere (`EM_DASH`).
- **Client names:** the blocklist is matched whole-word and case-insensitive against body text, filenames, and PDF/DOCX metadata (`CLIENT_NAME`).
- **JD copying:** any 8-word sequence shared between a bullet and the JD is rejected (`JD_COPY`).
- **Rendered length:** summary at most 4 lines, each bullet at most 3 lines (`TOO_LONG`).
  - Measure by building a ReportLab `Paragraph` with the block's style from `app/layout.py` and calling `wrap(AVAIL_WIDTH[block], large_height)`, then counting lines. Do not use `stringWidth` with a hand-written wrapper: that is a second implementation of line breaking and it will disagree with the renderer exactly at the boundary cases that matter.
  - Measurement input is the final marked-up text, inline bold included.
  - Use the same measurement as the DOCX proxy. See Section 7 on why that proxy is valid.
  - Only the summary and the bullet are length-checked. The header headline is the posting's exact job title and the role title is a real job title, so a limit on either would reject a truthful document with no available remedy. Overflow there is caught by `PAGE_COUNT_EXCEEDED` and the run report.
- **Unverifiable labels:** a self-description from `policy.unverifiable_labels`, such as "seasoned" or "proven track record", is rejected with `UNVERIFIABLE_LABEL`. Style bucket, 1 retry: it is not a false claim about a technology, it is a claim with no truth value at all, and dropping a bullet over an adjective would be a style rule deciding a question of fact. Checked in the summary and in bullets.
- **Title claims:** a job-title-shaped phrase in summary prose matching no title in `experience.json` reports `TITLE_CLAIM_UNVERIFIED`. Advisory, never a rejection. The header headline is the posting's exact job title and is exempt: applying for a role is not claiming to have held it.
- **Skills section:**
  - only confirmed entries with `depth` `built` or `used` (`SKILLS_EXPOSURE` rejects `exposure`)
  - no proficiency qualifiers anywhere in the section (`SKILLS_PROFICIENCY`): expert, advanced, proficient, intermediate, familiar, working knowledge, basic, or any "N years" construction

### G5 Round-trip gate (after rendering)

- **Text extraction:** extract text from the generated PDF and DOCX.
  - Every bullet, title, and section header must appear intact and in order (`ROUNDTRIP_TEXT_MISSING`, `ROUNDTRIP_ORDER`).
  - There must be no text in images, no layout tables, no content in headers or footers, and no multi-column flow (`ROUNDTRIP_STRUCTURE`).
- **Page count:** read the true page count from the rendered PDF and reject above `policy.max_pages`, default 2 (`PAGE_COUNT_EXCEEDED`). The remedy is to surface the overflow in the run report with the longest blocks ranked. Never auto-shrink font, leading, or margins to fit: that detaches the gate from the renderer.
- **Re-check:** run G1 through G4 on the extracted text. Rendering must not introduce anything.

### Rejection handling

Findings carry three independent properties: a **severity** (what it does to the block now), a **bucket** (which retry budget it draws from), and an **exhaustion** rule (what happens when that budget is spent).

- **Truth bucket** (G1, G2, G3, `CLIENT_NAME`, `JD_COPY`, `EM_DASH`): 2 retries, then the bullet is **dropped** and listed in the run report with its reasons.
- **Style bucket** (`OPENING_VERB_UNLISTED`, `TOO_LONG`, `BANNED_VERB`, `WEAK_OPENING`): 1 separate retry, then **render and flag**. A style rule must never drop a factually clean bullet.
- **Held** (`UNKNOWN_TERM`): not rendered until Yash approves it. Never auto-accepted.
- **Structure** (`BULLET_COUNT`, all of G5): not a per-block retry. The step reselects or fails visibly.
- **Schema failures:** model output that fails JSON schema validation gets 1 retry, then the step fails visibly.

Never fall back to a looser prompt or a relaxed gate.

### Soft targets (reported, never enforced)

Three measures are reported only and never trigger regeneration:
- number coverage (minimum 70%, target 90%)
- ATS score
- fit score

Enforcing coverage would push the model toward invented numbers. G3 would reject them, and the run would end in dropped bullets or in pressure on the user to "just confirm a number." That pressure is the failure this system exists to prevent.

## 6. Pipeline

Five steps. Each step is a separate request, with a human checkpoint before the next one.

Run state is persisted server-side under a run id. Closing Safari on the iPhone, or a dropped connection, loses nothing. No single request comes near the App Service front-end timeout (about 230 seconds).

### Step 1. Fit analysis

- **Model output:** a requirement-by-requirement table with columns for requirement, must-have or nice-to-have, canonical id, evidence id or "none", and verdict. Also the top missing keywords and the named gaps.
- **Deterministic ceiling:** code computes the share of must-have requirements covered by `confirmed` entries and experience facts. It is shown next to the model's 0 to 100 score. If the two differ by more than 15 points, show both and the reason.
- **Suggestion policy:** only a ledger entry explicitly marked `unconfirmed` may be surfaced as a gap Yash could verify. A canonical id absent from the ledger is blocked and never suggested. A `denied` id is reported only as "required by JD, not held."
- **Gap log:** every named gap is appended to `runs/gap_log` with a timestamp and canonical id.
- **Below threshold:** if the ceiling is below `fit_threshold` (default 60), the recommendation is "do not apply," with the gaps named. The user can override, and the override is recorded in the run report.

### Step 2. Bullet rewrite (XYZ)

- **Formula:** action verb, what was done, scope or scale, measured result, and business impact where the evidence supports it.
- **Vocabulary:** use the employer's exact terminology where it describes real, evidenced work, including terms approved in `synonyms.json`. Never swap in a synonym for the employer's term.
- **Order:** the most relevant bullet comes first within each role, not the most recent.
- **Output:** JSON bullets per role, each with `text`, `fact_ids`, and `metric_ids`. Every bullet passes G1 to G4 or is dropped.
- **Missing metrics:** these are flagged as questions for Yash to answer outside the run, by editing `experience.json`. The app never accepts a metric typed into the tailoring UI.

### Step 3. Skip-test

- **Model output:** what a human screener would skim past, plus a restructure plan.
- **Plan limits:** the plan may only reorder bullets, reselect from already-gated bullets, and edit the summary.
- **Re-gating:** any change to text goes back through G1 to G4.

### Step 4. Defensibility check (before rendering)

- **Model output:** for each bullet, the claim and the specific probe an interviewer would ask. The model does not write the answer.
- **Answers:** Yash answers in the UI, by typing or iPhone dictation. Answers are cached by bullet hash, so unchanged bullets reuse earlier answers.
- **Tests applied:**
  - Ten-minute test: could Yash talk about this for ten minutes?
  - Scope test: built, used, or exposure?
  - Number test: measured or recalled?
- **Deterministic caps:** applied in code, whatever the model or user verdict.
  - **Origin:** if the gap log shows a technology was named as a gap before its ledger `added` date, its origin is `after_gap`. Any bullet using it is capped at **Thin**.
  - **Cooling-off:** an `after_gap` entry added less than `cooling_off_hours` (default 72) before the run is treated as `unconfirmed` for that run.
  - **Recalled metrics:** any cited metric with `source: recalled` caps the bullet at **Thin**.
- **Verdict:** the model proposes Solid, Thin, or Cut, and Yash confirms.
  - Cut bullets are removed.
  - Thin bullets are rendered only if Yash explicitly keeps them.

### Step 5. ATS score, render, report

- **ATS score:** combines deterministic components with a model-judged component, weighted by `config/ats_rubric.json` (Yash approves the weights). The deterministic components are:
  - the G5 round-trip result
  - standard section headers
  - coverage of confirmed JD keywords
  - file format checks
- **Rendering:** produce the PDF (ReportLab) and DOCX (python-docx), then run G5.
- **Run report:** must include
  - bullet count per role
  - percentage of bullets carrying a number
  - every unquantified bullet
  - every gate rejection and dropped bullet, with reasons
  - the fit score and the deterministic ceiling
  - any user overrides
  - `computed.total_years_experience` and its anchor date
  - the hash of the evidence files used
  - `LAYOUT_VERSION`, so a CV generated under different geometry is identifiable later

## 7. Formatting (enforced in the generators)

- **Header:**
  - The exact target job title as the header headline.
  - The name in normal case, never all caps.
- **Location:**
  - If the posting's location is in `location_allowlist` (GTA cities, "Remote, Canada"), use it.
  - Otherwise use the default home location.
  - Never write a location Yash does not live in or is not relocating to.
- **Page:** US Letter, 0.75in margins, giving a 7.0in frame. Pass `pagesize=letter` explicitly; ReportLab's own default is A4 and must not be relied on.
- **Length:** summary at most 4 rendered lines, each bullet at most 3.
- **Spacing:**
  - Before each role title: 10pt in PDF, 200 twips in DOCX.
  - After each skills line: 5pt in PDF, 110 twips in DOCX.
- **Emphasis:** job titles in bold in both formats.
- **Layout:** single column, no layout tables, no text in headers or footers, no images.
- **Fonts:** PDF base-14 Helvetica at 10pt, not embedded, for maximum parser compatibility. DOCX uses Arial with a fallback chain of Helvetica then sans-serif.
  - Measuring the DOCX against Helvetica metrics is valid **only** because Arial and Helvetica are metric-compatible. If the DOCX font ever leaves that family, the proxy breaks and `TOO_LONG` stops describing the DOCX.
- **Metadata:** set PDF and DOCX metadata explicitly (title, author, subject, keywords, comments). Inherit nothing from templates.
- **Filenames:**
  - Pattern: `[Company]_[JobTitle]_Yash_Khamar_Resume.pdf`, and the same with `.docx`.
  - Replace spaces with `_`.
  - Strip `/ \ : * ? " < > |` and any `.` inside the title, so ".NET" becomes "NET".

### `app/layout.py` is the single source of truth

It owns every numeric constant and every `ParagraphStyle` object, and exports:
- `PAGE_SIZE`, `MARGINS`, `FRAME_WIDTH`
- a `STYLES` registry of `ParagraphStyle` objects (summary, bullet, role_title, skills_line, header)
- `AVAIL_WIDTH` per block type: frame width minus that block's left indent, bullet glyph and gap, or category label width
- `MAX_LINES` per block type
- `LAYOUT_VERSION`, an integer bumped on any change

The milestone 3 renderer imports these exact objects. It must not construct its own `ParagraphStyle` and must not restate any numeric constant. A test asserts the renderer's styles are the registry's objects **by identity**: a renderer that rebuilds a style with the same numbers passes an equality check and still drifts the moment one side is edited.

A golden test pins expected line counts for a fixture set of blocks. Any geometry change shows as a diff and forces a deliberate decision.

## 8. What the system refuses

- **Technologies:** anything not `confirmed`, or confirmed but outside its depth, contexts, or services.
- **Numbers:** any number not in the bullet's cited metrics, and any number at all in the summary or skills section that is not a computed value.
- **Style:** more than 3 bullets per role, banned phrases, em-dashes, client names, copied JD sentences.
- **Unsupported claims:** in bullets, the summary, or the skills section. G1 gates the skills section like everything else.
- **Score-chasing:** dropping a truthful fact to raise a score.
- **Stretching to fit:** when a role does not fit, the system says so and names the gaps.

## 9. Stack and security

- **Hosting:** FastAPI on Azure App Service (Linux, Python). Deploy with run-from-package, so the app directory, including `evidence/`, is read-only at runtime.
- **Model access:**
  - Use the Claude API through the official Python SDK.
  - Pin the model id in config, not scattered across files.
  - Enforce a per-run token budget in code.
- **Documents:** ReportLab for PDF and python-docx for DOCX. For G5 extraction, use pypdf (or pdfminer.six) and python-docx.
- **Storage:**
  - Outputs and run state go in Azure Blob Storage, in a private container accessed through managed identity.
  - Downloads use a user-delegation SAS with a 15-minute expiry, or are streamed through the API.
- **Authentication:** App Service Authentication (Entra ID), restricted to Yash's account. No anonymous route exists, including static files and downloads.
- **Secrets:**
  - The Anthropic API key lives in Azure Key Vault and is read through managed identity.
  - It is never in the repo, never in a committed `.env`, and never pasted into a Claude Code session.
  - Provide `.env.example` with placeholders only.
- **Mobile:** a responsive single page, with a web app manifest and icons so it installs to the iPhone home screen. No native app.
- **Logging:** log run ids, gate codes, and token usage. Do not log full CV or JD text to Application Insights.

## 10. Milestones (build in this order)

1. **Gates and tests.** Schemas for the evidence files, normalisation, G1 to G4, fixtures, and tests. No LLM, no web, no Azure.
   - **Historical fabrications:** each of the six is rejected in bullet, summary, and skills text. Include aliases, old product names, lowercase, hyphenated, and plural forms, for example:
     - "Azure OpenAI", "AOAI"
     - "Cognitive Search", "Azure AI Studio"
     - "Model Context Protocol", "retrieval-augmented generation"
   - **Taxonomy contract:** run against the real `vocab/taxonomy.json`, not a fixture.
     - every alias string resolves to exactly one canonical id
     - no alias of a distinct product resolves to an id confirmed in the ledger
   - **Ledger CI:** a diff that moves a `denied` entry to another state fails. So does deleting one.
   - **Numbers:** a number not in the cited metrics is rejected.
   - **Scope:** a build verb with a `used` technology is rejected, and a confirmed technology under the wrong role is rejected.
   - **Watch list:** a JD term absent from the evidence corpus is rejected, even when it is not in the taxonomy.
   - **Layout golden test:** pinned line counts for a fixture set of blocks, run here and again in milestone 3.
2. **Pipeline core.** Step schemas, prompts, model client, retry and drop logic split by bucket, run state, gap log, and run report. CLI only.
3. **Renderers and G5.** PDF, DOCX, metadata, filename rules, page count, and round-trip tests.
4. **Web app.** FastAPI routes, a step-by-step UI with checkpoints, defensibility answer capture, mobile layout, and the manifest.
5. **Azure.** App Service, Easy Auth, Key Vault, Blob Storage, managed identity, and the deploy pipeline. Deploy only after milestones 1 to 4 pass.

## 11. Ask Yash before deciding

- Taxonomy seed source and size.
- ATS rubric weights.
- The build-verb list, the weak-opener denylist, and the opening-verb coverage list.
- Anything in `evidence/` beyond schemas and fake examples.
- Any change to a gate's behaviour, threshold, or retry count from the defaults above.
- Any place where this spec seems to contradict itself.

### The bucket table

`app/gates/buckets.py` pins every code to a bucket, a severity and a retry budget, as a literal table. Moving a code between buckets requires editing that file, so a truth gate cannot be downgraded to advisory as a side effect of a refactor. A test asserts the table and the registry in `app/errors.py` agree in both directions, so neither a new code nor a changed one can slip through unlisted.

## 12. Decision log

Amendments to the original spec, with the reason each one was made. Every entry was decided by Yash under Section 11, except where marked.

**Layout and vocabulary moved out of `evidence/`.**
`taxonomy.json` moved to `vocab/`, and policy moved from `evidence/config.json` to `config/policy.json`. Neither holds a claim about what anyone did, so neither belongs among the evidence files. `evidence/` now holds exactly three files.

**Absence in the ledger is not suggestable.**
An id absent from the ledger is unconfirmed for gating, as before, and is now explicitly never offered as a gap to verify. Only an entry written as `unconfirmed` can be. Without this, Step 1 would hand back a shopping list of technologies to go and acquire, which is the pressure that produced the original incident.

**`WEAK_OPENING` became a denylist; the allowlist became coverage.**
Enforcing an allowlist means a style rule drops a truthful bullet over a verb nobody happened to list. The denylist rejects what is actually wrong, and `OPENING_VERB_UNLISTED` reports the gap with the config line to fix it.

**Retry budgets split by bucket.**
Truth findings get 2 retries and then drop. Style findings get 1 separate retry and then render and flag. A style rule must never drop a factually clean bullet, and a style finding must never consume the budget that would have saved one.

**`SCOPE_COHABITATION` added.**
Per-technology context checks cannot catch a sentence that blends two roles' work, because each technology in it is individually true.

**`SCOPE_EXPOSURE_IN_BULLET` and the skills rules added.**
Exposure-depth technologies are barred from bullet text and from the skills section entirely, and the skills section carries no proficiency qualifiers or years constructions.

**Computed-values registry added.**
The summary has no citations, so it carries no numbers, with one exception derived in code from the role dates. Without the exception the gate would reject an ordinary and truthful years-of-experience figure with no remedy available.

**`PAGE_COUNT_EXCEEDED` added to G5, `max_pages` default 2.**
The remedy is the run report, never an automatic shrink of font, leading, or margins: shrinking to fit detaches the gate from the renderer.

**Font decision recorded in Section 7.**
"Embedded standard fonts" replaced with base-14 Helvetica, not embedded. The DOCX proxy is valid only through Arial and Helvetica metric compatibility, which is now stated where it can be checked.

**Rejection codes the spec implied but did not name (decided by Claude Code, flagged for review):**
`CITATION_MISSING`, `CITATION_UNKNOWN`, `VERSION_UNSUPPORTED`, `SKILLS_PROFICIENCY`, and the G5 codes.

**Normalisation hardened beyond plain NFKC (decided by Claude Code, flagged for review).**
Decompose, drop combining marks and format characters, then recompose. A plain NFKC leaves a decomposed accent as two characters and a zero width space intact, either of which hides a technology name from every gate. This tightens matching; it relaxes nothing.

**Synonyms unlock wording, never a technology (decided by Claude Code, flagged for review).**
Section 4.4 says an entry lets a JD term appear when the literal term is absent from the evidence. Section 5 defines the corpus as containing the *targets*, which under a strict reading would mean no JD term is ever unlocked and the file does nothing. Both sides are now within reach of the watch-list check, and G1's taxonomy check runs independently so a synonym can never launder a denied id.

### Red team adjudication, fixture version 2

An independent adversarial fixture, authored outside the session that wrote the gates, was run against milestone 1. Fifteen of sixty-nine cases failed. The reviewer adjudicated every one. What changed:

**Gates that were wrong.** A homoglyph bypass, found by pulling on a case that *passed*: the tokeniser was ASCII-only, so a non-Latin letter acted as a separator rather than a character, and one Cyrillic `a` inside `RAG` produced no codes at all where the clean spelling produced `TECH_DENIED`. Fixed by G0, by Unicode-aware tokenisation, and by homoglyph folding applied after tokenisation. A zero width space joined two words into one token and lost a two-word alias; fixed by double-indexing aliases. A cited multiplier was held as an unknown product name; fixed by gate precedence. A hedge next to a number was unchecked inside bullets; fixed by applying hedges everywhere.

**Gates that did not exist.** `UNVERIFIABLE_LABEL`, `TITLE_CLAIM_UNVERIFIED`, and the load-time client blocklist check.

**Code names.** `VERSION_UNSUPPORTED` and `SKILLS_PROFICIENCY` were kept: they are more precise than the spec names, and the fixture changed instead. `SUMMARY_NUMBER_UNCITED` was renamed `UNCITED_NUMBER`, because it fires on skills lines too and the prefix was wrong.

**Cases that were wrong.** Three: a bullet whose evidence did not confirm the technology it tested, and two expecting bare "delivered" to be banned. "Delivered 12 services" is a real claim; "delivered on" is the empty one, and only the latter is banned.

### Red team adjudication, round 2, fixture version 3

Three findings from the first adjudication were themselves adjudicated.

**The hedge rule was wrong and is now positional.** "A hedge adjacent to any number" blocked "3x over the prior pipeline", which compares rather than hedges. Split into `leading_hedges` (before the number) and `trailing_hedges` (after it), with the computed years exemption scoped to the trailing rule alone.

**`NUMBER_FORM_MISMATCH` split from `NUMBER_UNSUPPORTED`.** An invented number and a correctly cited number in the wrong form are different defects and a retry should be told which.

**`SCOPE_COHABITATION` requires two participants.** The guard immediately exposed a test of this project's own that had been passing for the wrong reason: it read "Kafka streams" as the product Kafka Streams, so its sentence held one confirmed technology, not two.

### Round 3, preconditions

Every rejection test now asserts its own input before it reads a verdict. `tests/preconditions.py` holds one predicate per code, computed from structural facts or from the raw text and never from a gate's answer, because "the gate fired, therefore its input was present" is circular and restores exactly the blind spot the module exists to remove. Ten codes gained a paired "does not fire" case: a gate with only a firing test is half specified, and one that rejected everything would pass it.

### Round 4, fixture version 4

**`UNQUANTIFIED_SCALE` added, truth bucket.** A quantifier standing where a count belongs asserts a scale the evidence does not carry. Two boundaries were needed to keep it from rejecting truthful text: a countable noun in that position is a plural one, and a preposition ends the quantifier's phrase. The second was found by a test of this project's own, which caught "various tooling for order events" being rejected because the reach ran past the mass noun it modified and landed on a plural three tokens later.

**Bounds are measurements.** A hedged phrase a cited metric records verbatim is legal, and illegal everywhere else. Without it, a measured latency bound such as `under 200ms` could only be written by dropping the word that makes it true. It is the only hedge exemption besides the computed years form.

**`WEAK_OPENING` was already style bucket, 1 retry.** Checked rather than changed: the table said so already, and a cosmetic edit that looked like work would have been the wrong answer.

**The policy key is `vague_intensity_words`, not `intensity_words`.** Same four words, different name from the one the directive used.

**Open, not decided: digits inside an identifier.** `p95` and `p99` label which measurement was taken rather than claiming a scale, but their digits parse as numbers and the only exemption the spec grants is for digits inside a matched taxonomy alias. A truthful latency bullet is rejected today. Pinned by a characterisation test rather than patched, because the remedy is a spec decision about identifier-internal digits.
