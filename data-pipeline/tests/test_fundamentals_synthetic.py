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


def test_candidates_are_resolved_per_period_not_per_company(fallback_chain):
    """Each fiscal year is covered by a different candidate tag; all three are used."""
    series = quarterly_series(fallback_chain, "revenue")
    tags = {v.end.year: v.tag for v in series.values}

    assert tags[2022] == "SalesRevenueNet"
    assert tags[2024] == "Revenues"


def test_largest_candidate_wins_an_overlapping_period(fallback_chain):
    """2023 is covered by two tags at once, and the larger is the total.

    Alliance revenue, royalties and collaboration income sit outside ASC 606, so
    `RevenueFromContractWithCustomerExcludingAssessedTax` is a component of
    `Revenues`, not an alternative spelling of it. A total is at least as large
    as any component, so the larger figure is the one to report.
    """
    series = quarterly_series(fallback_chain, "revenue")
    q1_2023 = series.by_end()[D("2023-03-31")]

    assert q1_2023.tag == "Revenues"
    assert q1_2023.val == 70 * M  # not 20M, the contracts-with-customers component
    assert q1_2023.measurement_basis == "revenue_total"


def test_consistency_outranks_size_when_a_candidate_cannot_be_checked():
    """A component larger than its total means one of the two is not what it claims.

    This is Emergent's Q2 2021: the contracts-with-customers tag reports more
    than `Revenues` does, which is impossible. The larger figure belongs to a tag
    whose quarters never tile a fiscal year, so it cannot be reconciled, while
    `Revenues` reconciles exactly. Size alone would take the anomaly.
    """
    total = [100 * M, 100 * M, 100 * M, 100 * M]  # reconciles to a 400M annual
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": f"2024-{s}", "end": f"2024-{e}", "val": v, "form": "10-Q",
                             "accn": f"r{i}", "filed": "2025-01-01"}
                            for i, (s, e, v) in enumerate(
                                zip(["01-01", "04-01", "07-01", "10-01"],
                                    ["03-31", "06-30", "09-30", "12-31"], total)
                            )
                        ]
                        + [{"start": "2024-01-01", "end": "2024-12-31", "val": 400 * M,
                            "form": "10-K", "accn": "rfy", "filed": "2025-02-01"}]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {"start": "2024-04-01", "end": "2024-06-30", "val": 130 * M,
                             "form": "10-Q", "accn": "c1", "filed": "2025-01-01"}
                        ]
                    }
                },
            }
        }
    }
    q2 = quarterly_series(payload, "revenue").by_end()[D("2024-06-30")]

    assert q2.val == 100 * M  # the reconciling tag, despite 130M being larger
    assert q2.tag == "Revenues"


def test_chain_order_still_decides_for_non_total_concepts(ytd_only):
    """Only revenue uses largest-wins. R&D and OCF tags are not totals and components."""
    from transform.fundamentals import CONCEPT_CHAINS, Selection

    assert CONCEPT_CHAINS["revenue"].selection is Selection.LARGEST
    assert CONCEPT_CHAINS["rnd"].selection is Selection.CHAIN_ORDER
    assert CONCEPT_CHAINS["ocf"].selection is Selection.CHAIN_ORDER


def test_tag_is_recorded_on_every_value(fallback_chain):
    series = quarterly_series(fallback_chain, "revenue")

    assert all(v.tag for v in series.values)
    assert set(series.resolution.tags_used) == {v.tag for v in series.values}


def test_tags_used_is_reported_in_candidate_order(fallback_chain):
    """Determinism: the order mirrors the candidate list, not the order periods fall in."""
    resolution = quarterly_series(fallback_chain, "revenue").resolution

    assert resolution.tags_used == ("Revenues", "SalesRevenueNet")


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


def test_mixed_tag_flag_is_windowed_while_the_data_runs_further_back():
    """The flag is judged from 2019 on; the series still carries its full history.

    Nearly every filer crossed the ASC 606 revenue transition around 2018, so a
    flag computed over all history fires for the entire universe and stops
    meaning anything. Here the tag change is confined to 2017, so the series
    keeps those quarters and is not labelled mixed.
    """
    from transform.fundamentals import FLAG_WINDOW_START

    def year(tag, y, acc):
        ends = [("01-01", "03-31"), ("04-01", "06-30"), ("07-01", "09-30"), ("10-01", "12-31")]
        return [
            {"start": f"{y}-{s}", "end": f"{y}-{e}", "val": 10 * M, "form": "10-Q",
             "accn": f"{acc}{i}", "filed": f"{y + 1}-02-01"}
            for i, (s, e) in enumerate(ends)
        ]

    payload = {
        "facts": {
            "us-gaap": {
                "SalesRevenueNet": {"units": {"USD": year("s", 2017, "s")}},
                "Revenues": {"units": {"USD": year("r", 2021, "r") + year("r", 2022, "r")}},
            }
        }
    }
    series = quarterly_series(payload, "revenue")

    assert FLAG_WINDOW_START == D("2019-01-01")
    assert len(series.values) == 12  # 2017 quarters retained
    assert series.resolution.tags_used == ("Revenues", "SalesRevenueNet")
    assert "revenue:mixed_tags" not in series.flags


def test_tag_spans_record_where_each_tag_actually_applies(fallback_chain):
    """Scoping a flag to a span needs the span, not just a boolean."""
    spans = quarterly_series(fallback_chain, "revenue").tag_spans

    assert spans["SalesRevenueNet"] == (D("2022-03-31"), D("2022-12-31"))
    assert spans["Revenues"] == (D("2023-03-31"), D("2024-12-31"))


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
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert resolution.primary_tag == "Revenues"


def test_resolve_concept_names_near_misses_when_nothing_resolves():
    """A gap should say "the candidates do not list this filer's tag", not stay silent."""
    from transform.fundamentals import resolve_concept

    payload = {"facts": {"us-gaap": {"ResearchAndDevelopmentInProcess": {"units": {}}}}}
    resolution = resolve_concept(payload, "rnd")

    assert resolution.tags_available == ()
    assert resolution.near_miss_tags == ("ResearchAndDevelopmentInProcess",)


def test_unknown_concept_is_rejected(ytd_only):
    with pytest.raises(FundamentalsError, match="unknown concept"):
        quarterly_series(ytd_only, "ebitda")


def test_summed_concepts_add_their_components():
    """Total debt is `LongTermDebtNoncurrent + LongTermDebtCurrent`, not a chain."""
    def instant(tag, val):
        return {"units": {"USD": [
            {"end": "2026-06-30", "val": val, "form": "10-Q", "accn": tag, "filed": "2026-08-01"}
        ]}}

    series = quarterly_series(
        {"facts": {"us-gaap": {
            "LongTermDebtNoncurrent": instant("a", 900 * M),
            "LongTermDebtCurrent": instant("b", 100 * M),
        }}},
        "debt",
    )

    assert series.values[-1].val == 1_000 * M
    assert series.values[-1].contributing_tags == ("LongTermDebtNoncurrent", "LongTermDebtCurrent")
    assert "debt:incomplete_sum" not in series.flags


def test_a_missing_debt_component_is_flagged():
    """A filer with no current maturities and one that failed to tag them look alike."""
    series = quarterly_series(
        {"facts": {"us-gaap": {"LongTermDebtNoncurrent": {"units": {"USD": [
            {"end": "2026-06-30", "val": 900 * M, "form": "10-Q", "accn": "a", "filed": "2026-08-01"}
        ]}}}}},
        "debt",
    )

    assert series.values[-1].val == 900 * M
    assert "incomplete_sum" in series.values[-1].flags


def test_debt_aggregate_stands_in_when_no_component_is_tagged():
    """Novavax tags `LongTermDebt` and neither split; the aggregate must not double-count."""
    series = quarterly_series(
        {"facts": {"us-gaap": {"LongTermDebt": {"units": {"USD": [
            {"end": "2026-06-30", "val": 291 * M, "form": "10-Q", "accn": "a", "filed": "2026-08-01"}
        ]}}}}},
        "debt",
    )

    assert series.values[-1].val == 291 * M


def test_debt_aggregate_is_ignored_where_components_exist():
    def instant(tag, val):
        return {"units": {"USD": [
            {"end": "2026-06-30", "val": val, "form": "10-Q", "accn": tag, "filed": "2026-08-01"}
        ]}}

    series = quarterly_series(
        {"facts": {"us-gaap": {
            "LongTermDebtNoncurrent": instant("a", 900 * M),
            "LongTermDebtCurrent": instant("b", 100 * M),
            "LongTermDebt": instant("c", 1000 * M),
        }}},
        "debt",
    )

    assert series.values[-1].val == 1_000 * M  # not 2,000M


@pytest.mark.parametrize("concept", ["cash", "short_term_investments"])
def test_instant_concepts_resolve_without_raising(ytd_only, concept):
    """Balance-sheet concepts are supported now; the M2 pages need a cash column."""
    series = quarterly_series(ytd_only, concept)

    assert series.kind is ConceptKind.INSTANT
    assert series.values == ()  # this fixture carries no balance-sheet facts


def test_instant_values_are_read_at_the_date_they_are_struck():
    payload = {
        "facts": {
            "us-gaap": {
                "CashAndCashEquivalentsAtCarryingValue": {
                    "units": {
                        "USD": [
                            {"end": "2024-03-31", "val": 500 * M, "form": "10-Q",
                             "accn": "a", "filed": "2024-05-01"},
                            {"end": "2024-06-30", "val": 450 * M, "form": "10-Q",
                             "accn": "b", "filed": "2024-08-01"},
                        ]
                    }
                }
            }
        }
    }
    series = quarterly_series(payload, "cash")

    assert [(v.end, v.val) for v in series.values] == [
        (D("2024-03-31"), 500 * M),
        (D("2024-06-30"), 450 * M),
    ]
    assert all(v.start == v.end for v in series.values)


def test_balances_are_never_summed_into_a_trailing_total():
    """Four cash readings summed would report four times the cash on hand."""
    payload = {
        "facts": {
            "us-gaap": {
                "CashAndCashEquivalentsAtCarryingValue": {
                    "units": {
                        "USD": [
                            {"end": e, "val": 500 * M, "form": "10-Q", "accn": e, "filed": "2025-01-01"}
                            for e in ("2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31")
                        ]
                    }
                }
            }
        }
    }
    series = quarterly_series(payload, "cash")

    assert series.trailing_twelve_months() is None
    assert series.growth().value is None
    assert series.growth().suppressed_by == ("not_a_flow_concept",)


def test_concept_definitions_are_pinned():
    """A change here changes every downstream metric, so it must be deliberate.

    Two entries depart from the SPEC §5.1 table on purpose:

    * Revenue is a candidate set led by `Revenues`, not a chain led by the
      contracts-with-customers tag. SPEC's ordering treats a component as a
      preferred substitute for the total, which is wrong for pharma.
    * R&D carries both the including- and excluding-acquired-IPR&D tags, because
      SPEC's single entry left Pfizer and J&J with no R&D at all.
    """
    from transform.fundamentals import Selection

    assert CONCEPT_CHAINS["revenue"].tags == (
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert CONCEPT_CHAINS["revenue"].selection is Selection.LARGEST
    assert CONCEPT_CHAINS["rnd"].tags == (
        "ResearchAndDevelopmentExpense",
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    )
    assert CONCEPT_CHAINS["ocf"].tags == (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    )
    assert CONCEPT_CHAINS["debt"].kind is ConceptKind.SUM


def test_every_rnd_tag_declares_its_measurement_basis():
    """The two R&D tags are not interchangeable, so neither may travel unlabelled."""
    concept = CONCEPT_CHAINS["rnd"]

    assert set(concept.tag_basis) == set(concept.tags)
    assert concept.basis_of("ResearchAndDevelopmentExpense") == "rnd_including_acquired_iprd"
    assert (
        concept.basis_of("ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost")
        == "rnd_excluding_acquired_iprd"
    )


# --------------------------------------------------------------------------- #
# Guards against wrong arithmetic
# --------------------------------------------------------------------------- #


def test_a_year_to_date_minus_its_closing_quarter_gives_the_leading_stub():
    """The other direction of differencing: same end, different starts.

    Alnylam files a Q2 10-Q carrying the half-year and the discrete second
    quarter but no first-quarter year-to-date fact at all. Without this the
    first quarter is missing entirely, and a missing recent quarter nulls every
    trailing-twelve-month figure built on it — which nulled Alnylam's revenue,
    margins and R&D intensity despite $4.8bn of sales.
    """
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2026-01-01", "end": "2026-06-30", "val": 250 * M,
                             "form": "10-Q", "accn": "q2", "filed": "2026-07-30"},
                            {"start": "2026-04-01", "end": "2026-06-30", "val": 150 * M,
                             "form": "10-Q", "accn": "q2", "filed": "2026-07-30"},
                        ]
                    }
                }
            }
        }
    }
    quarters = quarterly_series(payload, "revenue").by_end()

    assert quarters[D("2026-03-31")].val == 100 * M
    assert quarters[D("2026-03-31")].start == D("2026-01-01")
    assert quarters[D("2026-03-31")].basis is Basis.DERIVED
    assert quarters[D("2026-06-30")].val == 150 * M


def test_same_end_differencing_still_refuses_a_non_quarter_residual():
    """A nine-month stub is not a quarter and must not be emitted as one."""
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2026-01-01", "end": "2026-12-31", "val": 400 * M,
                             "form": "10-K", "accn": "fy", "filed": "2027-02-01"},
                            {"start": "2026-10-01", "end": "2026-12-31", "val": 100 * M,
                             "form": "10-K", "accn": "fy", "filed": "2027-02-01"},
                        ]
                    }
                }
            }
        }
    }
    quarters = quarterly_series(payload, "revenue").by_end()

    # Q4 is reported; the 9-month residual is not a quarter and is not invented.
    assert set(quarters) == {D("2026-12-31")}


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


def test_overlapping_quarters_are_resolved_to_a_clean_tiling():
    """A filer inconsistent about where a period starts must not double-count.

    Pfizer is the real case: on its 52/53-week calendar Q1 2011 ends 3 April,
    but its Q2 2011 facts declare a start of 1 April, so the two quarters share
    two days. Both are reported figures, so the more recently filed wins.
    """
    from transform.fundamentals import FLAG_OVERLAPPING_PERIODS

    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2024-01-01", "end": "2024-04-03", "val": 100 * M,
                             "form": "10-Q", "accn": "q1", "filed": "2024-05-01"},
                            {"start": "2024-04-01", "end": "2024-07-03", "val": 110 * M,
                             "form": "10-Q", "accn": "q2", "filed": "2024-08-01"},
                        ]
                    }
                }
            }
        }
    }
    series = quarterly_series(payload, "revenue")

    assert len(series.values) == 1
    assert series.values[0].end == D("2024-07-03")  # the later filing wins
    assert f"revenue:{FLAG_OVERLAPPING_PERIODS}" in series.flags


def test_non_overlapping_quarters_are_all_kept(ytd_only):
    """The overlap guard must not thin out a clean series."""
    from transform.fundamentals import FLAG_OVERLAPPING_PERIODS

    series = quarterly_series(ytd_only, "revenue")

    assert len(series.values) == 4
    assert f"revenue:{FLAG_OVERLAPPING_PERIODS}" not in series.flags


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
