"""The gates. Every constraint in the spec, enforced by pure Python.

A gate reads only its inputs and the loaded evidence. It never calls a model and
never makes a network request. Prompts may repeat these rules as guidance, but
the gate is the only authority: nothing here asks a model whether its own output
passed.

G5, the round-trip gate, arrives with the renderer in milestone 3. Its rejection
codes are already registered in app.errors so the run report and the code table
do not have to be written twice.
"""

from __future__ import annotations

from app.errors import GateResult
from app.gates import g0_hygiene, g1_technology, g2_scope, g3_numbers, g4_structure
from app.gates.context import BlockAnalysis, GateContext, MatchedTech, TechResolution
from app.models import Block, Document

#: G0 first. It is a pre-gate: it reads the characters, the others read the
#: tokens those characters produced.
GATES = (g0_hygiene, g1_technology, g2_scope, g3_numbers, g4_structure)


def check_block(block: Block, ctx: GateContext) -> GateResult:
    """Run G1 through G4 over one block."""
    analysis = BlockAnalysis(block, ctx)
    return GateResult.merge(*(gate.check(analysis, ctx) for gate in GATES))


def check_document(document: Document, ctx: GateContext) -> GateResult:
    """Run every gate over a whole document, blocks and document-level alike."""
    results = [check_block(block, ctx) for block in document.blocks]
    results.append(g4_structure.check_document(document, ctx))
    return GateResult.merge(*results)


def analyse(block: Block, ctx: GateContext) -> BlockAnalysis:
    """The shared per-block analysis, for callers that need the matches."""
    return BlockAnalysis(block, ctx)


__all__ = [
    "BlockAnalysis",
    "GATES",
    "GateContext",
    "MatchedTech",
    "TechResolution",
    "analyse",
    "check_block",
    "check_document",
    "g0_hygiene",
    "g1_technology",
    "g2_scope",
    "g3_numbers",
    "g4_structure",
]
