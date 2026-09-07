"""Derived metrics (SPEC §6), and the two guards added ahead of M3.

The recurring theme is that a metric must decline to answer rather than answer
wrongly. Three cases here are worth more than the rest:

* a ratio must not pair a stale numerator with a current denominator;
* growth off a near-zero base is `n/m`, not a large percentage;
* runway must not be computed from cash the company cannot legally spend.
"""

from __future__ import annotations

import datetime as dt

import pytest

from transform.derive import (
    GROWTH_FLOOR,
    NOT_MEANINGFUL,
    NO_BURN,
    RESTRICTED_CASH_NOT_SEPARABLE,
    cash_runway_quarters,
    net_cash,
    operating_margin,
    revenue_growth,
    rnd_intensity,
)
from transform.fundamentals import quarterly_series

M = 1_000_000
QUARTER_ENDS = [("01-01", "03-31"), ("04-01", "06-30"), ("07-01", "09-30"), ("10-01", "12-31")]


def D(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def flows(tag, years: dict[int, list[float]]):
    return {tag: {"units": {"USD": [
        {"start": f"{y}-{s}", "end": f"{y}-{e}", "val": v, "form": "10-Q",
         "accn": f"{tag[:3]}{y}{i}", "filed": f"{y + 1}-02-01"}
        for y, vals in years.items()
        for i, ((s, e), v) in enumerate(zip(QUARTER_ENDS, vals))
    ]}}}


def balances(tag, values: dict[str, float]):
    return {tag: {"units": {"USD": [
        {"end": end, "val": v, "form": "10-Q", "accn": f"{tag[:3]}{end}", "filed": "2026-08-01"}
        for end, v in values.items()
    ]}}}


def payload(*groups):
    merged: dict = {}
    for g in groups:
        merged.update(g)
    return {"facts": {"us-gaap": merged}}


def series(doc, name):
    return quarterly_series(doc, name)


# --------------------------------------------------------------------------- #
# Growth floor
# --------------------------------------------------------------------------- #


def test_growth_off_a_trivial_base_is_not_meaningful():
    """Vir's shape: a tiny prior year makes the percentage describe the base."""
    doc = payload(flows("Revenues", {2025: [1 * M, 1 * M, 1 * M, 1 * M], 2026: [70 * M] * 4}))
    result = revenue_growth(series(doc, "revenue"), D("2026-12-31"))

    assert result.value is None
    assert result.suppressed_by == (NOT_MEANINGFUL,)


def test_growth_above_the_floor_is_reported():
    doc = payload(flows("Revenues", {2025: [20 * M] * 4, 2026: [40 * M] * 4}))
    result = revenue_growth(series(doc, "revenue"), D("2026-12-31"))

    assert result.value == pytest.approx(1.0)
    assert not result.suppressed


def test_the_floor_is_exactly_fifty_million():
    """Published on the methodology page, so it is pinned here."""
    assert GROWTH_FLOOR == 50_000_000.0


def test_vir_growth_is_suppressed_on_real_data(vir):
    result = revenue_growth(quarterly_series(vir, "revenue"))

    assert result.value is None
    assert NOT_MEANINGFUL in result.suppressed_by


# --------------------------------------------------------------------------- #
# Window alignment
# --------------------------------------------------------------------------- #


def test_a_stale_numerator_cannot_pair_with_a_current_denominator():
    """J&J's shape: operating income stops in 2015, revenue runs to 2026.

    Dividing one by the other produced a margin that described neither year.
    """
    doc = payload(
        flows("Revenues", {2025: [1000 * M] * 4, 2026: [1000 * M] * 4}),
        flows("OperatingIncomeLoss", {2015: [200 * M] * 4}),
    )
    result = operating_margin(series(doc, "operating_income"), series(doc, "revenue"))

    assert result.value is None
    assert result.suppressed_by == ("incomplete_window",)


def test_aligned_windows_produce_a_margin():
    doc = payload(
        flows("Revenues", {2026: [1000 * M] * 4}),
        flows("OperatingIncomeLoss", {2026: [200 * M] * 4}),
    )
    result = operating_margin(series(doc, "operating_income"), series(doc, "revenue"))

    assert result.value == pytest.approx(0.2)


def test_jnj_operating_margin_is_not_computed_from_stale_data(jnj):
    """Guard against the real regression, not just its synthetic shape."""
    result = operating_margin(quarterly_series(jnj, "operating_income"), quarterly_series(jnj, "revenue"))

    assert result.value is None


# --------------------------------------------------------------------------- #
# Operating income derivation
# --------------------------------------------------------------------------- #


def test_operating_income_is_reconstructed_where_the_subtotal_is_absent():
    """pre-tax income less the non-operating block, both from one filing."""
    doc = {
        "facts": {"us-gaap": {
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": {
                "units": {"USD": [
                    {"start": "2026-01-01", "end": "2026-03-31", "val": 300 * M,
                     "form": "10-Q", "accn": "same", "filed": "2026-05-01"}
                ]}
            },
            "NonoperatingIncomeExpense": {
                "units": {"USD": [
                    {"start": "2026-01-01", "end": "2026-03-31", "val": 50 * M,
                     "form": "10-Q", "accn": "same", "filed": "2026-05-01"}
                ]}
            },
        }}
    }
    result = series(doc, "operating_income")

    assert result.values[-1].val == 250 * M
    assert "derived_subtotal" in result.values[-1].flags
    assert result.values[-1].measurement_basis == "operating_income_derived"


def test_a_reported_subtotal_always_beats_a_reconstructed_one():
    doc = {
        "facts": {"us-gaap": {
            "OperatingIncomeLoss": {"units": {"USD": [
                {"start": "2026-01-01", "end": "2026-03-31", "val": 999 * M,
                 "form": "10-Q", "accn": "same", "filed": "2026-05-01"}
            ]}},
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": {
                "units": {"USD": [
                    {"start": "2026-01-01", "end": "2026-03-31", "val": 300 * M,
                     "form": "10-Q", "accn": "same", "filed": "2026-05-01"}
                ]}
            },
            "NonoperatingIncomeExpense": {"units": {"USD": [
                {"start": "2026-01-01", "end": "2026-03-31", "val": 50 * M,
                 "form": "10-Q", "accn": "same", "filed": "2026-05-01"}
            ]}},
        }}
    }
    value = series(doc, "operating_income").values[-1]

    assert value.val == 999 * M
    assert "derived_subtotal" not in value.flags


def test_the_two_sides_must_come_from_the_same_filing():
    """A subtotal stitched from two filings is a figure no filer ever asserted."""
    doc = {
        "facts": {"us-gaap": {
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": {
                "units": {"USD": [
                    {"start": "2026-01-01", "end": "2026-03-31", "val": 300 * M,
                     "form": "10-Q", "accn": "filing-a", "filed": "2026-05-01"}
                ]}
            },
            "NonoperatingIncomeExpense": {"units": {"USD": [
                {"start": "2026-01-01", "end": "2026-03-31", "val": 50 * M,
                 "form": "10-Q", "accn": "filing-b", "filed": "2026-05-02"}
            ]}},
        }}
    }

    assert series(doc, "operating_income").values == ()


# --------------------------------------------------------------------------- #
# Cash, net cash and runway
# --------------------------------------------------------------------------- #


def burn_doc(cash_tag: str, *, restricted: dict[str, float] | None = None):
    groups = [
        # A flat $50m burn each quarter, so the mean is $50m and the arithmetic
        # below can be checked by eye.
        flows("NetCashProvidedByUsedInOperatingActivities", {2026: [-50 * M] * 4}),
        balances(cash_tag, {"2026-12-31": 400 * M}),
    ]
    if restricted:
        groups.append(balances("RestrictedCashAndCashEquivalentsAtCarryingValue", restricted))
    return payload(*groups)


def test_runway_divides_liquid_assets_by_mean_quarterly_burn():
    doc = burn_doc("CashAndCashEquivalentsAtCarryingValue")
    result = cash_runway_quarters(series(doc, "cash"), series(doc, "ocf"))

    # $400m of cash against a $50m mean quarterly burn is eight quarters.
    assert result.value == pytest.approx(8.0)


def test_runway_is_null_when_the_company_generates_cash():
    doc = payload(
        flows("NetCashProvidedByUsedInOperatingActivities", {2026: [10 * M] * 4}),
        balances("CashAndCashEquivalentsAtCarryingValue", {"2026-12-31": 400 * M}),
    )
    result = cash_runway_quarters(series(doc, "cash"), series(doc, "ocf"))

    assert result.value is None
    assert result.suppressed_by == (NO_BURN,)


def test_restricted_cash_is_netted_off_where_the_filer_separates_it():
    doc = burn_doc(
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        restricted={"2026-12-31": 100 * M},
    )
    result = cash_runway_quarters(
        series(doc, "cash"), series(doc, "ocf"), None, series(doc, "restricted_cash")
    )

    # ($400m − $100m restricted) / $50m = six quarters, not eight.
    assert result.value == pytest.approx(6.0)


def test_runway_is_suppressed_where_restricted_cash_is_not_separable():
    """Gilead's shape: the broad cash tag, and no restricted-cash tag to net off."""
    doc = burn_doc("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")
    result = cash_runway_quarters(
        series(doc, "cash"), series(doc, "ocf"), None, series(doc, "restricted_cash")
    )

    assert result.value is None
    assert result.suppressed_by == (RESTRICTED_CASH_NOT_SEPARABLE,)


def test_net_cash_tolerates_the_broader_basis_but_flags_it():
    """A balance-sheet position, not a divisor, so an overstatement is survivable."""
    doc = burn_doc("CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")
    result = net_cash(series(doc, "cash"), None, series(doc, "debt"))

    assert result.value == pytest.approx(400 * M)
    assert "cash_includes_restricted" in result.flags


def test_net_cash_subtracts_debt():
    doc = payload(
        balances("CashAndCashEquivalentsAtCarryingValue", {"2026-12-31": 400 * M}),
        balances("LongTermDebtNoncurrent", {"2026-12-31": 250 * M}),
        balances("LongTermDebtCurrent", {"2026-12-31": 50 * M}),
    )
    result = net_cash(series(doc, "cash"), None, series(doc, "debt"))

    assert result.value == pytest.approx(100 * M)


def test_net_cash_flags_an_untagged_debt_position():
    doc = payload(balances("CashAndCashEquivalentsAtCarryingValue", {"2026-12-31": 400 * M}))
    result = net_cash(series(doc, "cash"), None, series(doc, "debt"))

    assert result.value == pytest.approx(400 * M)
    assert "debt_not_tagged" in result.flags


def test_gilead_cash_is_current_and_marked_broader(gild):
    """The 1,277-day gap closes, and the cost of closing it is recorded."""
    cash = quarterly_series(gild, "cash")

    assert cash.latest_period_end == D("2026-06-30")
    assert not cash.is_stale
    assert cash.values[-1].measurement_basis == "cash_including_restricted"
    assert "cash_includes_restricted" in cash.values[-1].flags


# --------------------------------------------------------------------------- #
# R&D intensity
# --------------------------------------------------------------------------- #


def test_rnd_intensity_uses_revenue_where_there_is_revenue():
    doc = payload(
        flows("Revenues", {2026: [250 * M] * 4}),
        flows("ResearchAndDevelopmentExpense", {2026: [50 * M] * 4}),
    )
    result = rnd_intensity(series(doc, "rnd"), series(doc, "revenue"))

    assert result.value == pytest.approx(0.2)


def test_rnd_intensity_falls_back_to_opex_for_a_pre_revenue_company():
    """SPEC §6 requires the variant, and requires it to be flagged."""
    doc = payload(
        flows("Revenues", {2026: [0, 0, 0, 0]}),
        flows("ResearchAndDevelopmentExpense", {2026: [50 * M] * 4}),
        flows("OperatingExpenses", {2026: [80 * M] * 4}),
    )
    result = rnd_intensity(series(doc, "rnd"), series(doc, "revenue"), series(doc, "opex"))

    assert result.value == pytest.approx(0.625)
    assert "rnd_intensity_over_opex" in result.flags


def test_rnd_intensity_is_null_with_no_usable_denominator():
    doc = payload(
        flows("Revenues", {2026: [0, 0, 0, 0]}),
        flows("ResearchAndDevelopmentExpense", {2026: [50 * M] * 4}),
    )
    result = rnd_intensity(series(doc, "rnd"), series(doc, "revenue"), None)

    assert result.value is None
    assert result.suppressed_by == ("no_denominator",)
