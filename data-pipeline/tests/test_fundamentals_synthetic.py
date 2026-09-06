"""Algorithm tests against hand-built payloads.

Every figure here is a round number chosen so the expected result can be checked
by eye, which is what makes these tests evidence rather than a restatement of the
implementation.
"""

from __future__ import annotations

import datetime as dt

import pytest

from transform.fundamentals import (
    CONCEPT_CHAINS,
    ConceptKind,
    Basis,
    FundamentalsError,
    UnsupportedConcept,
    build_quarterly_table,
    discrete_quarters,
    extract_facts,
    latest_by_period,
    quarterly_series,
)

M = 1_000_000


def D(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def values_by_end(series):
    return {v.end: v.val for v in series.values}


# --------------------------------------------------------------------------- #
# Year-to-date unwinding
# --------------------------------------------------------------------------- #


def test_ytd_revenue_is_differenced_into_discrete_quarters(ytd_only):
    """100 / 250 / 450 / 700 cumulative becomes 100 / 150 / 200 / 250 discrete."""
    series = quarterly_series(ytd_only, "revenue")

    assert values_by_end(series) == {
        D("2024-03-31"): 100 * M,
        D("2024-06-30"): 150 * M,
        D("2024-09-30"): 200 * M,
        D("2024-12-31"): 250 * M,
    }


def test_q4_comes_from_the_annual_minus_nine_months(ytd_only):
    """SPEC §5.1: Q4 is almost never filed on its own."""
    q4 = quarterly_series(ytd_only, "revenue").by_end()[D("2024-12-31")]

    assert q4.val == 250 * M
    assert q4.basis is Basis.DERIVED
    assert q4.start == D("2024-10-01")
    assert q4.derived_from == ((D("2024-01-01"), D("2024-12-31")), (D("2024-01-01"), D("2024-09-30")))
    assert q4.forms == ("10-K", "10-Q")


def test_first_quarter_is_reported_not_derived(ytd_only):
    """Q1 year-to-date and Q1 discrete are the same period, so no arithmetic is needed."""
    q1 = quarterly_series(ytd_only, "revenue").by_end()[D("2024-03-31")]

    assert q1.basis is Basis.REPORTED
    assert q1.derived_from == ()


def test_negative_operating_cash_flow_differences_correctly(ytd_only):
    """Burn is the normal case for clinical-stage names; signs must survive."""
    assert values_by_end(quarterly_series(ytd_only, "ocf")) == {
        D("2024-03-31"): -40 * M,
        D("2024-06-30"): -50 * M,
        D("2024-09-30"): -60 * M,
        D("2024-12-31"): -70 * M,
    }


def test_reported_quarter_wins_over_a_derivable_one(ytd_only):
    """R&D is filed both discretely and cumulatively; the filer's own quarter wins."""
    rnd = quarterly_series(ytd_only, "rnd").by_end()

    assert rnd[D("2024-06-30")].val == 20 * M
    assert rnd[D("2024-06-30")].basis is Basis.REPORTED
    # Q4 has no discrete fact, so it still has to be derived: 100 - 60.
    assert rnd[D("2024-12-31")].val == 40 * M
    assert rnd[D("2024-12-31")].basis is Basis.DERIVED


def test_derived_quarters_sum_back_to_the_reported_annual(ytd_only):
    series = quarterly_series(ytd_only, "revenue")

    assert [r.ok for r in series.reconciliations] == [True]
    assert series.reconciliations[0].annual == 700 * M
    assert series.reconciliations[0].quarters_sum == 700 * M


# --------------------------------------------------------------------------- #
# Form filtering
# --------------------------------------------------------------------------- #


def test_non_periodic_forms_are_excluded(ytd_only):
    """An 8-K carrying preliminary results must not enter the series (SPEC §5.1)."""
    series = quarterly_series(ytd_only, "revenue")

    assert D("2025-03-31") not in series.by_end()
    assert 999 * M not in values_by_end(series).values()


def test_the_8k_fact_is_present_in_the_fixture(ytd_only):
    """Guard the guard: the previous test would pass vacuously if the fact vanished."""
    raw = ytd_only["facts"]["us-gaap"]["Revenues"]["units"]["USD"]

    assert any(f["form"] == "8-K" and f["val"] == 999 * M for f in raw)


def test_amendments_are_kept(ytd_only):
    """10-K/A and 10-Q/A are restatements, not a different basis."""
    facts = extract_facts(ytd_only, "Revenues")
    assert {f.base_form for f in facts} == {"10-K", "10-Q"}
    assert all(f.form in {"10-K", "10-Q"} for f in facts)


# --------------------------------------------------------------------------- #
# Restatements
# --------------------------------------------------------------------------- #


def test_most_recently_filed_value_wins(restated):
    observed = latest_by_period(extract_facts(restated, "Revenues"))

    assert observed[(D("2024-01-01"), D("2024-12-31"))].val == 640 * M
    assert observed[(D("2024-01-01"), D("2024-09-30"))].val == 400 * M
    assert observed[(D("2024-01-01"), D("2024-12-31"))].accn == "new-fy"


def test_subtraction_never_mixes_vintages(restated):
    """Q4 must be 640 - 400. Mixing filings would give 300 or 190 instead."""
    q4 = quarterly_series(restated, "revenue").by_end()[D("2024-12-31")]

    assert q4.val == 240 * M
    assert q4.val not in (300 * M, 190 * M)


def test_restated_series_still_reconciles(restated):
    series = quarterly_series(restated, "revenue")

    assert values_by_end(series) == {
        D("2024-03-31"): 90 * M,
        D("2024-06-30"): 140 * M,
        D("2024-09-30"): 170 * M,
        D("2024-12-31"): 240 * M,
    }
    assert sum(values_by_end(series).values()) == 640 * M
    assert all(r.ok for r in series.reconciliations)


# --------------------------------------------------------------------------- #
# Chain resolution
# --------------------------------------------------------------------------- #


def test_chain_is_walked_per_period_not_per_company(fallback_chain):
    """Each fiscal year is covered by a different chain entry; all three are used."""
    series = quarterly_series(fallback_chain, "revenue")
    tags = {v.end.year: v.tag for v in series.values}

    assert tags[2022] == "SalesRevenueNet"
    assert tags[2023] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert tags[2024] == "Revenues"


def test_chain_order_decides_an_overlapping_period(fallback_chain):
    """2023 is covered by two tags at once; the earlier chain entry must win."""
    series = quarterly_series(fallback_chain, "revenue")
    q1_2023 = series.by_end()[D("2023-03-31")]

    assert q1_2023.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert q1_2023.val == 20 * M  # not 70M, which is what `Revenues` carries
    assert "Revenues" in series.resolution.tags_available


def test_tag_is_recorded_on_every_value(fallback_chain):
    series = quarterly_series(fallback_chain, "revenue")

    assert all(v.tag for v in series.values)
    assert set(series.resolution.tags_used) == {v.tag for v in series.values}


def test_tags_used_is_reported_in_chain_order(fallback_chain):
    """Determinism: the order mirrors SPEC §5.1, not the order periods happen to fall in."""
    resolution = quarterly_series(fallback_chain, "revenue").resolution

    assert resolution.tags_used == (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    )


def test_fallback_and_mixed_tags_are_flagged(fallback_chain):
    """SPEC §6: a metric off a non-primary tag has to be footnotable."""
    series = quarterly_series(fallback_chain, "revenue")

    assert series.resolution.uses_fallback
    assert series.resolution.mixed
    assert "revenue:fallback_tag" in series.flags
    assert "revenue:mixed_tags" in series.flags


def test_primary_only_series_is_not_flagged_as_fallback(ytd_only):
    series = quarterly_series(ytd_only, "rnd")

    assert series.resolution.tags_used == ("ResearchAndDevelopmentExpense",)
    assert not series.resolution.uses_fallback
    assert series.flags == ()


# --------------------------------------------------------------------------- #
# Trailing twelve months
# --------------------------------------------------------------------------- #


def test_ttm_sums_four_contiguous_quarters(ytd_only):
    ttm = quarterly_series(ytd_only, "revenue").trailing_twelve_months()

    assert ttm.val == 700 * M
    assert (ttm.start, ttm.end) == (D("2024-01-01"), D("2024-12-31"))


def test_ttm_refuses_to_span_a_tag_change(fallback_chain):
    """A TTM straddling two tags compares two definitions; better to return nothing."""
    series = quarterly_series(fallback_chain, "revenue")

    assert series.trailing_twelve_months(D("2024-12-31")).val == 126 * M  # 30+31+32+33
    assert series.trailing_twelve_months(D("2023-03-31")) is None  # 2022 tag + 2023 tag


def test_tags_are_interchangeable_only_on_evidence(fallback_chain):
    """Tags whose histories never overlap cannot be shown equivalent, so they are not.

    `SalesRevenueNet` covers 2022 alone and never appears alongside another tag,
    so no pair involving it qualifies. `Revenues` and the primary tag both cover
    2023 and disagree, so they are excluded too.
    """
    series = quarterly_series(fallback_chain, "revenue")

    assert series.interchangeable == frozenset()
    assert {(d.start.year, d.end.year) for d in series.divergences} == {(2023, 2023)}


def test_ttm_returns_none_when_a_quarter_is_missing(restated):
    series = quarterly_series(restated, "revenue")

    assert series.trailing_twelve_months(D("2024-09-30")) is None


# --------------------------------------------------------------------------- #
# Table assembly and scope
# --------------------------------------------------------------------------- #


def test_table_rows_carry_tag_and_basis_per_concept(ytd_only):
    table = build_quarterly_table(ytd_only)
    row = {r.period_end: r for r in table.rows}[D("2024-12-31")]

    assert row.values == {"revenue": 250 * M, "rnd": 40 * M, "ocf": -70 * M}
    assert row.source_tags["revenue"] == "Revenues"
    assert row.source_basis == {"revenue": "derived", "rnd": "derived", "ocf": "derived"}


def test_table_serialises_to_the_spec_shape(ytd_only):
    payload = build_quarterly_table(ytd_only).to_dict()
    row = payload["quarterly"][0]

    assert payload["cik"] == "0009000001"
    assert set(row) >= {"period_start", "period_end", "revenue", "rnd", "ocf", "source_tags"}
    assert row["period_end"] == "2024-03-31"


def test_missing_concept_leaves_a_null_rather_than_dropping_the_row(restated):
    """Restated Corp files revenue only; the row must still exist."""
    table = build_quarterly_table(restated)
    row = table.rows[0]

    assert row.values["revenue"] is not None
    assert row.values["rnd"] is None
    assert row.source_tags["rnd"] is None
    assert "rnd:no_tag_resolved" in table.flags


def test_since_filters_rows(fallback_chain):
    table = build_quarterly_table(fallback_chain, since=D("2024-01-01"))

    assert [r.period_end.year for r in table.rows] == [2024, 2024, 2024, 2024]


def test_flags_describe_the_requested_window_not_all_history(fallback_chain):
    """A window sitting on one tag is not a mixed-tag series.

    Nearly every filer crossed the ASC 606 revenue transition around 2018, so
    flags computed over full history fire for the entire universe and stop
    meaning anything. Narrowing to 2024 leaves only `Revenues` in play.
    """
    full = build_quarterly_table(fallback_chain)
    windowed = build_quarterly_table(fallback_chain, since=D("2024-01-01"))

    assert "revenue:mixed_tags" in full.flags
    assert "revenue:mixed_tags" not in windowed.flags
    assert windowed.series["revenue"].resolution.tags_used == ("Revenues",)


def test_windowing_does_not_change_the_figures(fallback_chain):
    """Derivation still runs over every fact; only the reported window narrows."""
    full = quarterly_series(fallback_chain, "revenue").by_end()
    windowed = quarterly_series(fallback_chain, "revenue", since=D("2024-01-01")).by_end()

    assert set(windowed) < set(full)
    assert all(windowed[end].val == full[end].val for end in windowed)


def test_q4_still_derivable_when_the_window_starts_mid_year(ytd_only):
    """The nine-month figure needed for Q4 falls outside the window and must still be read."""
    series = quarterly_series(ytd_only, "revenue", since=D("2024-12-01"))

    assert [v.end for v in series.values] == [D("2024-12-31")]
    assert series.values[0].val == 250 * M


def test_resolve_concept_reports_availability_without_computing(fallback_chain):
    from transform.fundamentals import resolve_concept

    resolution = resolve_concept(fallback_chain, "revenue")

    assert resolution.resolved is False  # nothing used yet
    assert resolution.tags_available == (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    )
    assert resolution.primary_tag == "RevenueFromContractWithCustomerExcludingAssessedTax"


def test_resolve_concept_names_near_misses_when_nothing_resolves(fallback_chain):
    """A gap should say "the chain does not list this filer's tag", not stay silent."""
    from transform.fundamentals import resolve_concept

    payload = {"facts": {"us-gaap": {"ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost": {"units": {}}}}}
    resolution = resolve_concept(payload, "rnd")

    assert resolution.tags_available == ()
    assert resolution.near_miss_tags == (
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    )


def test_unknown_concept_is_rejected(ytd_only):
    with pytest.raises(FundamentalsError, match="unknown concept"):
        quarterly_series(ytd_only, "ebitda")


@pytest.mark.parametrize("concept", ["cash", "short_term_investments", "debt"])
def test_non_duration_concepts_are_out_of_m1_scope(ytd_only, concept):
    """SPEC §5.1 defines them; M1 implements the duration concepts only."""
    with pytest.raises(UnsupportedConcept):
        quarterly_series(ytd_only, concept)


def test_chain_definitions_match_the_spec():
    """SPEC §5.1, transcribed. A change here changes every downstream metric."""
    assert CONCEPT_CHAINS["revenue"].tags == (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    )
    assert CONCEPT_CHAINS["rnd"].tags == ("ResearchAndDevelopmentExpense",)
    assert CONCEPT_CHAINS["ocf"].tags == (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    )
    assert CONCEPT_CHAINS["debt"].kind is ConceptKind.SUM


# --------------------------------------------------------------------------- #
# Guards against wrong arithmetic
# --------------------------------------------------------------------------- #


def test_half_year_gaps_are_not_split_into_quarters():
    """A six-month residual is not a quarter, so nothing may be inferred from it."""
    facts = extract_facts(
        {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"start": "2024-01-01", "end": "2024-03-31", "val": 100 * M,
                                 "form": "10-Q", "accn": "a", "filed": "2024-05-01"},
                                {"start": "2024-01-01", "end": "2024-09-30", "val": 450 * M,
                                 "form": "10-Q", "accn": "b", "filed": "2024-11-01"},
                            ]
                        }
                    }
                }
            }
        },
        "Revenues",
    )
    quarters = discrete_quarters(facts)

    assert set(quarters) == {D("2024-03-31")}


def test_periods_with_different_starts_are_never_differenced():
    """Only same-start cumulative periods may be subtracted."""
    facts = extract_facts(
        {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"start": "2024-01-01", "end": "2024-06-30", "val": 250 * M,
                                 "form": "10-Q", "accn": "a", "filed": "2024-08-01"},
                                {"start": "2024-01-08", "end": "2024-09-30", "val": 450 * M,
                                 "form": "10-Q", "accn": "b", "filed": "2024-11-01"},
                            ]
                        }
                    }
                }
            }
        },
        "Revenues",
    )

    assert discrete_quarters(facts) == {}


def test_instant_facts_are_ignored_by_duration_extraction():
    """A balance-sheet fact has no `start` and must not be read as a period."""
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"end": "2024-03-31", "val": 5 * M, "form": "10-Q",
                             "accn": "a", "filed": "2024-05-01"},
                        ]
                    }
                }
            }
        }
    }

    assert extract_facts(payload, "Revenues") == []
    assert len(extract_facts(payload, "Revenues", duration_only=False)) == 1
