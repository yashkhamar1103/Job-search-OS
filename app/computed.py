"""Code-computed values.

A number in the summary or the skills section has no citation to check it
against, so the only numbers permitted there are ones this module derives from
experience.json. The model never supplies them and cannot widen this registry.

Today that is one value: total years of experience.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.loaders import Experience

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _ordinal(month: str) -> int:
    match = _MONTH_RE.match(month)
    if not match:
        raise ValueError(f"not a YYYY-MM month: {month!r}")
    year, mon = int(match.group(1)), int(match.group(2))
    return year * 12 + (mon - 1)


def _ordinal_of(when: date) -> int:
    return when.year * 12 + (when.month - 1)


@dataclass(frozen=True)
class ComputedValues:
    """Values derived from the evidence, anchored to a run date."""

    total_years: int
    union_months: int
    anchor: date

    @property
    def allowed_year_renderings(self) -> tuple[tuple[str, ...], ...]:
        """The exact token sequences a summary may use for total years.

        N years and N+ years, as specified. The singular is additionally allowed
        when N is one, because one years is not English and the alternative
        would be a gate no truthful text can satisfy.
        """
        n = self.total_years
        forms = [(str(n), "years"), (f"{n}+", "years")]
        if n == 1:
            forms += [(str(n), "year"), (f"{n}+", "year")]
        return tuple(forms)


def total_years_experience(experience: Experience, *, anchor: date | None = None) -> ComputedValues:
    """Years of experience, counting overlapping roles once and gaps not at all.

    Education is not counted because it is not in experience.json at all. A role
    with no end date is treated as running to the anchor month.

    The union is computed over distinct months rather than by summing durations,
    so two concurrent roles contribute the months they actually span, once.
    """
    anchor = anchor or date.today()
    anchor_ordinal = _ordinal_of(anchor)

    months: set[int] = set()
    for role in experience.roles:
        start = _ordinal(role.start)
        if role.is_current:
            end = anchor_ordinal
        else:
            end = _ordinal(str(role.end))
        if end < start:
            raise ValueError(f"role {role.id!r} ends before it starts")
        end = min(end, anchor_ordinal)
        if end < start:
            # The whole role is in the future relative to the anchor.
            continue
        months.update(range(start, end + 1))

    union_months = len(months)
    return ComputedValues(
        total_years=union_months // 12,
        union_months=union_months,
        anchor=anchor,
    )
