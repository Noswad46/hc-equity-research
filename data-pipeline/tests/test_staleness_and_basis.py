"""The two guards added before M2, both from the M1 review.

**Staleness.** Gilead's including-IPR&D R&D tag stops in 2020. Before the R&D
candidates were widened, its latest trailing-twelve-month window was a 2019-20
one presented as current, with nothing on the record saying so. Widening the
candidates fixed that instance; it did not fix the class, because any filer that
abandons a tag reproduces it. The guard compares each concept's latest period
against the most recent period the filer reports anything for.

**Basis cutover.** Per-value basis labels stop one company being compared with
another on the wrong footing, but they say nothing about a single company's
series changing basis partway through — which renders as a step change that
never happened. The cutover marker names where that occurs.
"""

from __future__ import annotations

import datetime as dt

from transform.fundamentals import (
    STALE_TOLERANCE_DAYS,
    basis_segments,
    latest_reported_period_end,
    quarterly_series,
)

M = 1_000_000


def D(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def quarterly_facts(tag, year, *, val=100 * M, form="10-Q"):
    ends = [("01-01", "03-31"), ("04-01", "06-30"), ("07-01", "09-30"), ("10-01", "12-31")]
    return [
        {"start": f"{year}-{s}", "end": f"{year}-{e}", "val": val, "form": form,
         "accn": f"{tag[:4]}{year}{i}", "filed": f"{year + 1}-02-01"}
        for i, (s, e) in enumerate(ends)
    ]


def payload(tags: dict[str, list]):
    return {"facts": {"us-gaap": {t: {"units": {"USD": f}} for t, f in tags.items()}}}


# --------------------------------------------------------------------------- #
# Reference point
# --------------------------------------------------------------------------- #


def test_reference_is_the_filers_most_recent_reported_period():
    doc = payload(
        {
            "Revenues": quarterly_facts("Revenues", 2020),
            "SomeOtherTag": quarterly_facts("Other", 2026),
        }
    )

    assert latest_reported_period_end(doc) == D("2026-12-31")


def test_reference_ignores_non_periodic_forms():
    doc = payload({"Revenues": quarterly_facts("Revenues", 2026, form="8-K")})

    assert latest_reported_period_end(doc) is None


def test_reference_is_drawn_from_every_tag_not_just_tracked_concepts():
    """If it came only from tracked tags, a wholesale tag change would look current."""
    doc = payload(
        {
            "Revenues": quarterly_facts("Revenues", 2019),
            "SomeUntrackedDisclosure": quarterly_facts("Untracked", 2026),
        }
    )

    assert latest_reported_period_end(doc) == D("2026-12-31")


# --------------------------------------------------------------------------- #
# Staleness
# --------------------------------------------------------------------------- #


def test_abandoned_tag_is_flagged_stale():
    """The Gilead shape: the concept's tag stops, the filer keeps reporting."""
    doc = payload(
        {
            "Revenues": quarterly_facts("Revenues", 2020),
            "SomeOtherTag": quarterly_facts("Other", 2026),
        }
    )
    series = quarterly_series(doc, "revenue")

    assert series.latest_period_end == D("2020-12-31")
    assert series.reference_period_end == D("2026-12-31")
    assert series.is_stale
    assert series.staleness_days > STALE_TOLERANCE_DAYS
    assert "revenue:stale_series" in series.flags


def test_a_current_series_is_not_flagged():
    doc = payload({"Revenues": quarterly_facts("Revenues", 2026)})
    series = quarterly_series(doc, "revenue")

    assert series.staleness_days == 0
    assert not series.is_stale
    assert "revenue:stale_series" not in series.flags


def test_one_quarter_of_lag_is_tolerated():
    """A concept can appear in the 10-K and not the following 10-Q without being stale."""
    doc = payload(
        {
            "Revenues": quarterly_facts("Revenues", 2025),
            "SomeOtherTag": quarterly_facts("Other", 2025)
            + [
                {"start": "2026-01-01", "end": "2026-03-31", "val": 1, "form": "10-Q",
                 "accn": "x", "filed": "2026-05-01"}
            ],
        }
    )
    series = quarterly_series(doc, "revenue")

    assert series.staleness_days == 90
    assert not series.is_stale


def test_staleness_is_unknown_without_values():
    doc = payload({"SomeOtherTag": quarterly_facts("Other", 2026)})
    series = quarterly_series(doc, "revenue")

    assert series.latest_period_end is None
    assert series.staleness_days is None
    assert not series.is_stale


def test_gilead_style_stale_concept_is_caught_on_real_data(jnj):
    """J&J stopped tagging OperatingIncomeLoss long ago; the guard must say so."""
    series = quarterly_series(jnj, "operating_income")

    assert series.values == () or series.is_stale


# --------------------------------------------------------------------------- #
# Basis segments and cutover
# --------------------------------------------------------------------------- #


def test_single_basis_series_has_one_segment_and_no_cutover(mrna):
    series = quarterly_series(mrna, "rnd")
    segments, cutovers = basis_segments(series.values)

    assert len(segments) == 1
    assert segments[0].basis == "rnd_including_acquired_iprd"
    assert cutovers == []
    assert "rnd:basis_cutover" not in series.flags


def test_vertex_rnd_basis_cutover_is_identified(vrtx):
    """Vertex reports R&D including acquired IPR&D, then excluding it."""
    series = quarterly_series(vrtx, "rnd")

    assert len(series.segments) == 2
    assert [s.basis for s in series.segments] == [
        "rnd_including_acquired_iprd",
        "rnd_excluding_acquired_iprd",
    ]
    assert len(series.cutovers) == 1
    cutover = series.cutovers[0]
    assert cutover.last_end_before == D("2022-03-31")
    assert cutover.first_end_after == D("2022-06-30")
    assert "rnd:basis_cutover" in series.flags


def test_cutover_names_the_periods_either_side(vrtx):
    """The presentation layer needs the boundary, not just the fact of one."""
    cutover = quarterly_series(vrtx, "rnd").cutovers[0].to_dict()

    assert cutover["from_basis"] == "rnd_including_acquired_iprd"
    assert cutover["to_basis"] == "rnd_excluding_acquired_iprd"
    assert cutover["last_period_end_before"] < cutover["first_period_end_after"]


def test_segments_tile_the_series_without_gaps(vrtx):
    series = quarterly_series(vrtx, "rnd")
    covered = sum(s.count for s in series.segments)

    assert covered == len([v for v in series.values if v.measurement_basis])


def test_bases_are_recorded_and_not_normalised(vrtx):
    """No adjustment factor, no blending — the two bases stay as reported."""
    series = quarterly_series(vrtx, "rnd")
    before = [v for v in series.values if v.end == D("2022-03-31")][0]
    after = [v for v in series.values if v.end == D("2022-06-30")][0]

    assert before.measurement_basis != after.measurement_basis
    assert before.contributing_bases == (before.measurement_basis,)
    assert after.contributing_bases == (after.measurement_basis,)


def test_basis_segments_skips_values_without_a_basis():
    from transform.fundamentals import Basis, PeriodValue

    values = [
        PeriodValue(
            concept="x", tag="T", start=D("2024-01-01"), end=D("2024-03-31"), val=1.0,
            basis=Basis.REPORTED, filed=D("2024-05-01"), accns=("a",), forms=("10-Q",),
        )
    ]
    segments, cutovers = basis_segments(values)

    assert segments == []
    assert cutovers == []
