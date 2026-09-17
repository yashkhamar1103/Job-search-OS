"""The document shape the gates read.

A Block is one gateable unit of text. The block type selects which gates apply
and which line limit and paragraph style the length check uses, so it is not
cosmetic: a bullet and a summary line are checked by different rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app import layout

BULLET = "bullet"
SUMMARY = "summary"
SKILLS_LINE = "skills_line"
ROLE_TITLE = "role_title"
HEADER = "header"

#: Blocks that carry claims. G1 runs over every one of them, because the skills
#: section and the summary are gated like everything else.
CLAIM_BLOCKS = frozenset({BULLET, SUMMARY, SKILLS_LINE})

#: Blocks that cite evidence and therefore may carry numbers.
CITING_BLOCKS = frozenset({BULLET})


@dataclass(frozen=True)
class Block:
    """One gateable unit of text."""

    block_type: str
    text: str
    block_id: str = ""
    role_id: str | None = None
    fact_ids: tuple[str, ...] = ()
    metric_ids: tuple[str, ...] = ()
    markup: str | None = None
    """Final marked-up text for measurement, inline bold included. When absent,
    the plain text is escaped and measured, which is correct for a block with no
    inline emphasis."""

    skills_category: str | None = None

    def __post_init__(self) -> None:
        if self.block_type not in layout.STYLES:
            raise ValueError(f"unknown block type: {self.block_type!r}")
        if self.block_type == BULLET and not self.role_id:
            raise ValueError(f"bullet {self.block_id!r} has no role_id")

    @property
    def measurable_markup(self) -> str:
        return self.markup if self.markup is not None else layout.escape_markup(self.text)

    @property
    def cites(self) -> bool:
        return self.block_type in CITING_BLOCKS


@dataclass(frozen=True)
class Document:
    """A tailored CV as the gates see it, before rendering."""

    blocks: tuple[Block, ...] = ()
    target_job_title: str = ""
    company: str = ""
    location: str = ""
    filename_stem: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def of_type(self, block_type: str) -> tuple[Block, ...]:
        return tuple(b for b in self.blocks if b.block_type == block_type)

    def bullets_by_role(self) -> dict[str, tuple[Block, ...]]:
        out: dict[str, list[Block]] = {}
        for block in self.of_type(BULLET):
            out.setdefault(block.role_id or "", []).append(block)
        return {role: tuple(items) for role, items in out.items()}
