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


def test_a_single_role_counts_inclusive_months():
    """2022-06 to 2024-05 is 24 months, which is two years."""
    computed = total_years_experience(Experience((_role("a", "2022-06", "2024-05"),)), anchor=ANCHOR)
    assert computed.union_months == 24
    assert computed.total_years == 2


def test_overlapping_roles_are_counted_once():
    """Two concurrent roles are not four years of experience."""
    assert _years(_role("a", "2022-01", "2023-12"), _role("b", "2022-01", "2023-12")) == 2


def test_partially_overlapping_roles_count_the_union():
    assert _years(_role("a", "2022-01", "2022-12"), _role("b", "2022-07", "2023-06")) == 1


def test_gaps_are_excluded():
    """One year, a three-year gap, then one year, is two years."""
    assert _years(_role("a", "2018-01", "2018-12"), _role("b", "2022-01", "2022-12")) == 2


def test_a_current_role_is_anchored_to_the_run_date():
    assert _years(_role("a", "2024-04", None)) == 2
    assert _years(_role("a", "2024-04", "present")) == 2


def test_the_total_is_floored_not_rounded():
    """23 months is one year, not two. Rounding up is a claim nobody made."""
    computed = total_years_experience(Experience((_role("a", "2022-06", "2024-04"),)), anchor=ANCHOR)
    assert computed.union_months == 23
    assert computed.total_years == 1


def test_a_role_ending_after_the_anchor_is_clipped():
    assert _years(_role("a", "2025-04", "2030-01")) == 1


def test_the_anchor_is_reported_so_the_run_report_can_print_it():
    computed = total_years_experience(Experience((_role("a", "2022-01", "2022-12"),)), anchor=ANCHOR)
    assert computed.anchor == ANCHOR


def test_a_role_ending_before_it_starts_is_an_error():
    with pytest.raises(ValueError):
        total_years_experience(Experience((_role("a", "2024-01", "2023-01"),)), anchor=ANCHOR)


def test_allowed_renderings_are_n_years_and_n_plus_years():
    computed = total_years_experience(Experience((_role("a", "2022-01", "2024-12"),)), anchor=ANCHOR)
    assert computed.total_years == 3
    assert ("3", "years") in computed.allowed_year_renderings
    assert ("3+", "years") in computed.allowed_year_renderings
    assert ("4", "years") not in computed.allowed_year_renderings


def test_the_singular_is_allowed_only_at_one_year():
    one = total_years_experience(Experience((_role("a", "2025-01", "2025-12"),)), anchor=ANCHOR)
    assert one.total_years == 1
    assert ("1", "year") in one.allowed_year_renderings

    three = total_years_experience(Experience((_role("a", "2022-01", "2024-12"),)), anchor=ANCHOR)
    assert ("3", "year") not in three.allowed_year_renderings


def test_the_fixture_world_totals_what_the_role_dates_say(bundle):
    """acme 2022-06 to 2024-05 and bolt 2024-06 to 2026-03: 46 months, 3 years."""
    computed = total_years_experience(bundle.experience, anchor=ANCHOR)
    assert computed.union_months == 46
    assert computed.total_years == 3
