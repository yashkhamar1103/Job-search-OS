"""Rejection codes, severities, retry buckets, and the Rejection record.

Every gate returns Rejection objects carrying a code from CODES and the span of
the offending text, measured against the caller's original untouched string.

Three axes are attached to each code and they are deliberately independent:

  severity    What the finding does to the block right now.
  bucket      Which retry budget the finding draws from.
  exhaustion  What happens after that budget is spent.

The truth and style split exists so a style rule can never drop a factually
clean bullet. Truth findings drop the bullet after their retries. Style findings
render the bullet and flag it in the run report.

Milestone 1 defines and assigns these. Milestone 2 owns the retry loop that
consumes them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Codes for gates that do not exist yet are defined here anyway. A single
# registry is the only way a run report can render a finding it did not
# hard-code, and it keeps milestone 3 from inventing a parallel vocabulary.


class Severity(str, Enum):
    """What a finding does to the block it was raised against."""

    REJECT = "reject"
    """Blocks the text. It is regenerated, then dropped or flagged."""

    HOLD = "hold"
    """Not rendered until Yash approves the item. Never auto-accepted."""

    ADVISORY = "advisory"
    """Never blocks. Reported so a config gap is visible and fixable."""


class Bucket(str, Enum):
    """Which retry budget a finding draws from."""

    TRUTH = "truth"
    STYLE = "style"
    STRUCTURE = "structure"
    """Not a per-block retry. The step reselects or fails visibly."""


class Exhaustion(str, Enum):
    """What happens once a finding's retry budget is spent."""

    DROP = "drop"
    RENDER_AND_FLAG = "render_and_flag"
    HOLD_FOR_REVIEW = "hold_for_review"
    FAIL_STEP = "fail_step"


class Gate(str, Enum):
    G0 = "G0"
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"
    G4 = "G4"
    G5 = "G5"
    SCHEMA = "schema"


@dataclass(frozen=True)
class CodeSpec:
    code: str
    gate: Gate
    severity: Severity
    bucket: Bucket
    exhaustion: Exhaustion
    description: str
    retries: int | None = None
    """Per-code retry budget. None means the bucket's budget from policy.
    Zero means no retry at all: some defects are not the kind of thing a
    regeneration fixes, and retrying them only launders the attempt."""


def _spec(
    code: str,
    gate: Gate,
    severity: Severity,
    bucket: Bucket,
    exhaustion: Exhaustion,
    description: str,
    retries: int | None = None,
) -> CodeSpec:
    return CodeSpec(code, gate, severity, bucket, exhaustion, description, retries)


_ALL: tuple[CodeSpec, ...] = (
    # G0 text hygiene. Runs before every other gate, on generated text only.
    #
    # Zero retries on all three. A homoglyph or an invisible character is not a
    # phrasing problem that a regeneration fixes, and none of them is ever
    # auto-corrected: silently repairing the text would hide the fact that
    # something produced it in the first place.
    _spec(
        "INVISIBLE_CHAR",
        Gate.G0,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A zero-width, invisible, or bidi control character appears in the text. "
        "Such a character can hide a technology name from every gate that reads "
        "tokens.",
        retries=0,
    ),
    _spec(
        "MIXED_SCRIPT",
        Gate.G0,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A single token mixes characters from more than one Unicode script, which "
        "is how a homoglyph is smuggled into an otherwise Latin word.",
        retries=0,
    ),
    _spec(
        "NON_LATIN_SCRIPT",
        Gate.G0,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A letter outside the Latin script appears in generated text. Latin "
        "Extended accented characters remain legal.",
        retries=0,
    ),

    # G1 technology. All truth.
    _spec(
        "TECH_UNCONFIRMED",
        Gate.G1,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A taxonomy term maps to a canonical id that is not confirmed in the ledger.",
    ),
    _spec(
        "TECH_DENIED",
        Gate.G1,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A taxonomy term maps to a canonical id denied in the ledger.",
    ),
    _spec(
        "JD_TERM_NOT_IN_EVIDENCE",
        Gate.G1,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A term drawn from the job description appears in output but is absent "
        "from the evidence corpus.",
    ),
    _spec(
        "UNKNOWN_TERM",
        Gate.G1,
        Severity.HOLD,
        Bucket.TRUTH,
        Exhaustion.HOLD_FOR_REVIEW,
        "A proper-noun-shaped token is in neither the taxonomy nor the evidence "
        "corpus. Held for Yash, never rendered unapproved.",
    ),
    # G2 scope. All truth.
    _spec(
        "SCOPE_DEPTH",
        Gate.G2,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A build verb shares a bullet with a technology whose depth is not built.",
    ),
    _spec(
        "SCOPE_CONTEXT",
        Gate.G2,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A technology appears under a role that is not in its contexts.",
    ),
    _spec(
        "SCOPE_SERVICE",
        Gate.G2,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A named sub-service is not in the platform entry's services list.",
    ),
    _spec(
        "SCOPE_EXPOSURE_IN_BULLET",
        Gate.G2,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A technology with depth exposure appears in bullet text. Exposure may "
        "appear only on a separate environment line.",
    ),
    _spec(
        "SCOPE_COHABITATION",
        Gate.G2,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "Technologies sharing a sentence have no role in common, so the sentence "
        "blends work from different roles.",
    ),
    # G3 numbers. All truth.
    _spec(
        "NUMBER_UNSUPPORTED",
        Gate.G3,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A numeric expression in a bullet does not equal a value in the bullet's "
        "cited metrics.",
    ),
    _spec(
        "VAGUE_METRIC",
        Gate.G3,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A vague intensity word implies a number that does not exist.",
    ),
    _spec(
        "VERSION_UNSUPPORTED",
        Gate.G3,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A version number attached to a technology is not in that entry's "
        "versions list.",
    ),
    _spec(
        "CITATION_MISSING",
        Gate.G3,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A bullet cites no fact_id.",
    ),
    _spec(
        "CITATION_UNKNOWN",
        Gate.G3,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A cited fact_id or metric_id is not in experience.json.",
    ),
    _spec(
        "UNCITED_NUMBER",
        Gate.G3,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A number appears in a block that carries no citations, so nothing ties "
        "it to evidence. Fires on the summary and on skills lines alike, which "
        "is why the name carries no SUMMARY prefix.",
    ),
    # G4 structure and style.
    _spec(
        "BULLET_COUNT",
        Gate.G4,
        Severity.REJECT,
        Bucket.STRUCTURE,
        Exhaustion.FAIL_STEP,
        "A role carries more than the configured maximum number of bullets. Not "
        "a per-bullet retry: the step reselects.",
    ),
    _spec(
        "BANNED_VERB",
        Gate.G4,
        Severity.REJECT,
        Bucket.STYLE,
        Exhaustion.RENDER_AND_FLAG,
        "A banned phrase appears in the text.",
    ),
    _spec(
        "WEAK_OPENING",
        Gate.G4,
        Severity.REJECT,
        Bucket.STYLE,
        Exhaustion.RENDER_AND_FLAG,
        "The bullet opens with a weak opener, an -ing or -ly word, a form of be "
        "or have, or has no verb in its first two tokens.",
    ),
    _spec(
        "OPENING_VERB_UNLISTED",
        Gate.G4,
        Severity.ADVISORY,
        Bucket.STYLE,
        Exhaustion.RENDER_AND_FLAG,
        "The opening verb passed the denylist but is absent from "
        "policy.opening_verbs. Coverage signal only. Never rejects.",
    ),
    _spec(
        "EM_DASH",
        Gate.G4,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "An em dash, horizontal bar, or double hyphen appears in the text.",
    ),
    _spec(
        "CLIENT_NAME",
        Gate.G4,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A blocklisted client name appears in body text, a filename, or document "
        "metadata.",
    ),
    _spec(
        "JD_COPY",
        Gate.G4,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A word sequence of the configured length is shared with the job "
        "description.",
    ),
    _spec(
        "TOO_LONG",
        Gate.G4,
        Severity.REJECT,
        Bucket.STYLE,
        Exhaustion.RENDER_AND_FLAG,
        "The block wraps to more rendered lines than its type allows.",
    ),
    _spec(
        "UNVERIFIABLE_LABEL",
        Gate.G4,
        Severity.REJECT,
        Bucket.STYLE,
        Exhaustion.RENDER_AND_FLAG,
        "An unverifiable self-description, such as seasoned or proven track "
        "record. It asserts a quality no evidence can support or refute.",
        retries=1,
    ),
    _spec(
        "TITLE_CLAIM_UNVERIFIED",
        Gate.G4,
        Severity.ADVISORY,
        Bucket.STYLE,
        Exhaustion.RENDER_AND_FLAG,
        "A job-title-shaped phrase in summary prose matches no title in "
        "experience.json. Reported, never rejected: the header headline is the "
        "posting's title and is exempt.",
    ),
    _spec(
        "SKILLS_EXPOSURE",
        Gate.G4,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A technology with depth exposure appears in the skills section.",
    ),
    _spec(
        "SKILLS_PROFICIENCY",
        Gate.G4,
        Severity.REJECT,
        Bucket.TRUTH,
        Exhaustion.DROP,
        "A proficiency qualifier or a years construction appears in the skills "
        "section.",
    ),
    # G5 round trip. Milestone 3 implements these. Registered now so the run
    # report and the code table do not have to be edited twice.
    _spec(
        "ROUNDTRIP_TEXT_MISSING",
        Gate.G5,
        Severity.REJECT,
        Bucket.STRUCTURE,
        Exhaustion.FAIL_STEP,
        "Text present in the gated document did not survive extraction from the "
        "rendered file.",
    ),
    _spec(
        "ROUNDTRIP_ORDER",
        Gate.G5,
        Severity.REJECT,
        Bucket.STRUCTURE,
        Exhaustion.FAIL_STEP,
        "Extracted text is out of document order.",
    ),
    _spec(
        "ROUNDTRIP_STRUCTURE",
        Gate.G5,
        Severity.REJECT,
        Bucket.STRUCTURE,
        Exhaustion.FAIL_STEP,
        "The rendered file contains a structure an ATS parser mishandles: text "
        "in images, layout tables, header or footer content, or multi-column "
        "flow.",
    ),
    _spec(
        "PAGE_COUNT_EXCEEDED",
        Gate.G5,
        Severity.REJECT,
        Bucket.STRUCTURE,
        Exhaustion.FAIL_STEP,
        "The rendered PDF has more pages than policy.max_pages. Never remedied "
        "by shrinking font, leading, or margins.",
    ),
    # Schema.
    _spec(
        "SCHEMA_INVALID",
        Gate.SCHEMA,
        Severity.REJECT,
        Bucket.STRUCTURE,
        Exhaustion.FAIL_STEP,
        "Model output failed JSON schema validation.",
    ),
)

CODES: dict[str, CodeSpec] = {spec.code: spec for spec in _ALL}


@dataclass(frozen=True)
class Span:
    """A half-open character range in the caller's original untouched text."""

    start: int
    end: int
    text: str

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid span {self.start}:{self.end}")


@dataclass(frozen=True)
class Rejection:
    """One finding from one gate."""

    code: str
    span: Span
    detail: str = ""
    block_id: str = ""
    context: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code not in CODES:
            raise ValueError(f"unregistered rejection code: {self.code}")

    @property
    def spec(self) -> CodeSpec:
        return CODES[self.code]

    @property
    def severity(self) -> Severity:
        return self.spec.severity

    @property
    def bucket(self) -> Bucket:
        return self.spec.bucket

    @property
    def blocks_render(self) -> bool:
        return self.severity in (Severity.REJECT, Severity.HOLD)

    def __str__(self) -> str:
        where = f"{self.span.start}:{self.span.end}"
        detail = f" {self.detail}" if self.detail else ""
        return f"{self.code} [{where}] {self.span.text!r}{detail}"


@dataclass(frozen=True)
class GateResult:
    """The outcome of running one or more gates over one block.

    A gate returns pass or a list of rejections. `passed` is true only when no
    finding blocks rendering. Advisory findings are carried but do not fail.
    """

    rejections: tuple[Rejection, ...] = ()

    @property
    def passed(self) -> bool:
        return not any(r.blocks_render for r in self.rejections)

    @property
    def blocking(self) -> tuple[Rejection, ...]:
        return tuple(r for r in self.rejections if r.blocks_render)

    @property
    def advisories(self) -> tuple[Rejection, ...]:
        return tuple(r for r in self.rejections if not r.blocks_render)

    def codes(self) -> tuple[str, ...]:
        return tuple(r.code for r in self.rejections)

    def __add__(self, other: "GateResult") -> "GateResult":
        return GateResult(self.rejections + other.rejections)

    @staticmethod
    def merge(*results: "GateResult") -> "GateResult":
        out: list[Rejection] = []
        for result in results:
            out.extend(result.rejections)
        return GateResult(tuple(out))


PASS = GateResult()
