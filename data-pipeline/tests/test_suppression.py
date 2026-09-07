"""Flags must suppress downstream metrics, not merely annotate them.

Solving the confident-looking-wrong-number problem at the fact layer is only half
of it. If a flagged period can still feed a growth calculation, the bad number
reappears one layer up as a percentage, where it is much harder to spot — a
footnote is easy to drop on the way to a table cell, and a null is not.

`guard_metric` is the general mechanism, built here before the derived metrics of
SPEC §6 exist so they can be routed through it rather than retrofitted.
"""

from __future__ import annotations

import datetime as dt

import pytest

from transform.fundamentals import (
    BLOCKING_FLAGS,
    FLAG_RESTATED_FISCAL_YEAR,
    FLAG_TAG_BASIS_UNCERTAIN,
    Basis,
    MetricResult,
    PeriodValue,
    guard_metric,
    quarterly_series,
)

M = 1_000_000


def D(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def value(end: str, val: float = 100 * M, *flags: str) -> PeriodValue:
    end_date = D(end)
    return PeriodValue(
        concept="revenue",
        tag="Revenues",
        start=end_date - dt.timedelta(days=89),
        end=end_date,
        val=val,
        basis=Basis.REPORTED,
        filed=end_date,
        accns=("a",),
        forms=("10-Q",),
        flags=flags,
    )


# --------------------------------------------------------------------------- #
# The mechanism
# --------------------------------------------------------------------------- #


def test_clean_inputs_produce_a_value():
    result = guard_metric("demo", lambda: 1.5, [value("2024-03-31"), value("2024-06-30")])

    assert result.value == 1.5
    assert result.suppressed is False
    assert result.suppressed_by == ()


def test_a_blocking_flag_on_any_input_suppresses_the_metric():
    inputs = [value("2024-03-31"), value("2024-06-30", 100 * M, FLAG_RESTATED_FISCAL_YEAR)]
    result = guard_metric("demo", lambda: 1.5, inputs)

    assert result.value is None
    assert result.suppressed is True
    assert result.suppressed_by == (FLAG_RESTATED_FISCAL_YEAR,)


def test_suppression_does_not_evaluate_the_metric():
    """The thunk must not run on inputs that were never fit to use."""
    calls = []

    def compute():
        calls.append(1)
        return 1.0

    guard_metric("demo", compute, [value("2024-03-31", 1, FLAG_RESTATED_FISCAL_YEAR)])

    assert calls == []


def test_non_blocking_flags_annotate_without_suppressing():
    """`tag_basis_uncertain` marks ambiguity, not error, so it must not null a metric."""
    inputs = [value("2024-03-31", 100 * M, FLAG_TAG_BASIS_UNCERTAIN)]
    result = guard_metric("demo", lambda: 2.0, inputs)

    assert result.value == 2.0
    assert FLAG_TAG_BASIS_UNCERTAIN in result.flags
    assert result.suppressed is False
    assert FLAG_TAG_BASIS_UNCERTAIN not in BLOCKING_FLAGS


def test_the_blocking_set_is_caller_configurable():
    """A stricter caller can widen it without the fact layer changing."""
    inputs = [value("2024-03-31", 100 * M, FLAG_TAG_BASIS_UNCERTAIN)]
    result = guard_metric(
        "demo", lambda: 2.0, inputs, blocking=frozenset({FLAG_TAG_BASIS_UNCERTAIN})
    )

    assert result.value is None
    assert result.suppressed_by == (FLAG_TAG_BASIS_UNCERTAIN,)


def test_no_inputs_is_itself_a_suppression():
    result = guard_metric("demo", lambda: 1.0, [])

    assert result.value is None
    assert result.suppressed_by == ("no_inputs",)


def test_result_serialises():
    result = guard_metric("demo", lambda: 0.25, [value("2024-03-31")])
    payload = result.to_dict()

    assert payload["value"] == 0.25
    assert payload["suppressed"] is False
    assert payload["period_ends"] == ["2024-03-31"]


def test_flags_are_collected_without_duplicates():
    inputs = [
        value("2024-03-31", 1, FLAG_TAG_BASIS_UNCERTAIN),
        value("2024-06-30", 1, FLAG_TAG_BASIS_UNCERTAIN),
    ]

    assert guard_metric("demo", lambda: 1.0, inputs).flags == (FLAG_TAG_BASIS_UNCERTAIN,)


# --------------------------------------------------------------------------- #
# Growth, the first caller
# --------------------------------------------------------------------------- #


def test_growth_is_computed_from_clean_quarters(ytd_only):
    """Only one year exists, so there is no prior window to compare against."""
    result = quarterly_series(ytd_only, "revenue").growth()

    assert result.value is None
    assert result.suppressed_by == ("incomplete_window",)


def test_growth_over_two_clean_years():
    def year(y, vals):
        ends = [("01-01", "03-31"), ("04-01", "06-30"), ("07-01", "09-30"), ("10-01", "12-31")]
        return [
            {"start": f"{y}-{s}", "end": f"{y}-{e}", "val": v, "form": "10-Q",
             "accn": f"{y}{i}", "filed": f"{y + 1}-02-01"}
            for i, ((s, e), v) in enumerate(zip(ends, vals))
        ]

    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {"USD": year(2023, [100 * M] * 4) + year(2024, [125 * M] * 4)}
                }
            }
        }
    }
    result = quarterly_series(payload, "revenue").growth(D("2024-12-31"))

    assert result.value == pytest.approx(0.25)
    assert result.suppressed is False
    assert len(result.inputs) == 8


def test_merck_growth_spanning_the_restated_year_is_null(mrk):
    """Merck's FY2020 was restated for the Organon spin-off; its quarters were not.

    The quarters are still emitted — they are what Merck filed — but a
    year-on-year comparison across them measures a divestment rather than
    trading, so it must be null rather than a footnoted percentage.
    """
    series = quarterly_series(mrk, "revenue")

    for as_of in ("2020-12-31", "2021-12-31"):
        result = series.growth(D(as_of))
        assert result.value is None, as_of
        assert FLAG_RESTATED_FISCAL_YEAR in result.suppressed_by, as_of


def test_merck_still_emits_the_restated_quarters(mrk):
    """Suppression applies to metrics. The underlying data must survive."""
    index = quarterly_series(mrk, "revenue").by_end()
    fy2020 = [index[D(e)] for e in ("2020-03-31", "2020-06-30", "2020-09-30", "2020-12-31")]

    assert all(q.val > 0 for q in fy2020)
    assert all(FLAG_RESTATED_FISCAL_YEAR in q.flags for q in fy2020)


def test_merck_growth_outside_the_restated_year_is_computed(mrk):
    """The suppression has to be specific, or it is just a broken metric."""
    result = quarterly_series(mrk, "revenue").growth(D("2023-12-31"))

    assert result.value is not None
    assert result.suppressed is False


def test_restated_flag_reaches_the_row_output(mrk):
    from transform.fundamentals import build_quarterly_table

    table = build_quarterly_table(mrk)
    row = {r.period_end: r for r in table.rows}[D("2020-06-30")]

    assert f"revenue:{FLAG_RESTATED_FISCAL_YEAR}" in row.flags


def test_growth_result_is_a_metric_result(mrk):
    assert isinstance(quarterly_series(mrk, "revenue").growth(), MetricResult)
