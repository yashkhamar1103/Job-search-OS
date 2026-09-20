"""The computed-values registry."""

from __future__ import annotations

from datetime import date

import pytest

from app.computed import total_years_experience
from app.loaders import Experience, Fact, Role

ANCHOR = date(2026, 3, 31)


def _role(role_id: str, start: str, end: str | None) -> Role:
    return Role(
        id=role_id,
        employer=f"{role_id} Inc",
        title="Engineer",
        start=start,
        end=end,
        location="",
        facts=(Fact(f"{role_id}-f1", "did a thing"),),
        metrics=(),
    )


def _years(*roles: Role) -> int:
    return total_years_experience(Experience(roles), anchor=ANCHOR).total_years


def test_a_single_role_counts_elapsed_months_not_inclusive_ones():
    """2022-06 to 2024-05 spans 24 calendar months and counts as 23.

    Elapsed, not inclusive. A role starting on the 30th of its start month and
    ending on the 1st of its end month touches both months without working
    either, so inclusive counting overstates by up to two. Discounting one is
    the conservative reading, and this number goes on a CV.
    """
    computed = total_years_experience(Experience((_role("a", "2022-06", "2024-05"),)), anchor=ANCHOR)
    assert computed.union_months == 23
    assert computed.total_years == 1


def test_overlapping_roles_are_counted_once():
    """Two concurrent roles are not four years of experience."""
    computed = total_years_experience(
        Experience((_role("a", "2022-01", "2023-12"), _role("b", "2022-01", "2023-12"))),
        anchor=ANCHOR,
    )
    assert computed.union_months == 23
    assert computed.total_years == 1


def test_partially_overlapping_roles_count_the_union():
    assert _years(_role("a", "2022-01", "2022-12"), _role("b", "2022-07", "2023-06")) == 1


def test_gaps_are_excluded():
    """Two twelve-month stretches, three years apart, count 11 + 11."""
    computed = total_years_experience(
        Experience((_role("a", "2018-01", "2018-12"), _role("b", "2022-01", "2022-12"))),
        anchor=ANCHOR,
    )
    assert computed.union_months == 22
    assert computed.total_years == 1


def test_back_to_back_roles_are_one_stretch_and_lose_one_month_not_two():
    """The subtraction is per continuous stretch, never per role.

    Two adjacent roles at one employer are one period of employment with one
    partial month at each end. Discounting a month per role would invent a gap
    in the boundary month, which was worked. This is the difference between
    Amnex counting 77 months and 75.
    """
    contiguous = total_years_experience(
        Experience((_role("a", "2018-06", "2019-05"), _role("b", "2019-06", "2024-11"))),
        anchor=ANCHOR,
    )
    assert contiguous.union_months == 77

    one_role_same_span = total_years_experience(
        Experience((_role("a", "2018-06", "2024-11"),)), anchor=ANCHOR
    )
    assert one_role_same_span.union_months == 77


def test_a_current_role_is_anchored_to_the_run_date():
    """2024-04 to the 2026-03 anchor is 23 elapsed months."""
    assert _years(_role("a", "2024-04", None)) == 1
    assert _years(_role("a", "2024-04", "present")) == 1


def test_the_total_is_floored_not_rounded():
    """23 months is one year, not two. Rounding up is a claim nobody made."""
    computed = total_years_experience(Experience((_role("a", "2022-06", "2024-06"),)), anchor=ANCHOR)
    assert computed.union_months == 24
    assert computed.total_years == 2

    just_under = total_years_experience(Experience((_role("a", "2022-06", "2024-05"),)), anchor=ANCHOR)
    assert just_under.union_months == 23
    assert just_under.total_years == 1


def test_a_role_ending_after_the_anchor_is_clipped():
    """Clipped to the anchor month, then counted elapsed: 2025-04 to 2026-03."""
    computed = total_years_experience(Experience((_role("a", "2025-04", "2030-01"),)), anchor=ANCHOR)
    assert computed.union_months == 11
    assert computed.total_years == 0


def test_a_role_inside_a_single_month_counts_nothing():
    """Start and end in the same month is a partial month, which is zero
    elapsed months. Conservative by construction."""
    computed = total_years_experience(Experience((_role("a", "2025-04", "2025-04"),)), anchor=ANCHOR)
    assert computed.union_months == 0
    assert computed.total_years == 0


def test_the_anchor_is_reported_so_the_run_report_can_print_it():
    computed = total_years_experience(Experience((_role("a", "2022-01", "2022-12"),)), anchor=ANCHOR)
    assert computed.anchor == ANCHOR


def test_a_role_ending_before_it_starts_is_an_error():
    with pytest.raises(ValueError):
        total_years_experience(Experience((_role("a", "2024-01", "2023-01"),)), anchor=ANCHOR)


def test_allowed_renderings_are_n_years_and_n_plus_years():
    computed = total_years_experience(Experience((_role("a", "2022-01", "2025-01"),)), anchor=ANCHOR)
    assert computed.total_years == 3
    assert ("3", "years") in computed.allowed_year_renderings
    assert ("3+", "years") in computed.allowed_year_renderings
    assert ("4", "years") not in computed.allowed_year_renderings


def test_the_singular_is_allowed_only_at_one_year():
    one = total_years_experience(Experience((_role("a", "2025-01", "2026-01"),)), anchor=ANCHOR)
    assert one.total_years == 1
    assert ("1", "year") in one.allowed_year_renderings

    three = total_years_experience(Experience((_role("a", "2022-01", "2025-01"),)), anchor=ANCHOR)
    assert three.total_years == 3
    assert ("3", "year") not in three.allowed_year_renderings


def test_the_fixture_world_totals_what_the_role_dates_say(bundle):
    """acme 2022-06 to 2024-05 and bolt 2024-06 to 2026-03 are back to back,
    so they are one stretch: 2022-06 to 2026-03 is 45 elapsed months."""
    computed = total_years_experience(bundle.experience, anchor=ANCHOR)
    assert computed.union_months == 45
    assert computed.total_years == 3
