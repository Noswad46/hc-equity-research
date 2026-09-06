"""Tests against real `companyfacts` payloads and published figures.

SPEC §5.1: "Write unit tests for this against two or three companies with known
figures before trusting anything downstream."

The fixtures are trimmed SEC responses — the chain tags only, from 2018 onward,
with the raw fact records untouched. The figures asserted here are the ones the
companies actually reported, which is what makes these tests worth having: an
algorithm that merely reconciles with itself would pass a self-consistency check
and still be wrong.

Each company was chosen for a specific failure mode:

* Moderna — clean calendar year, cash flow filed year-to-date only.
* Merck — FY2020 restated for the Organon spin-off above unrestated quarters.
* Pfizer — 52/53-week calendar, R&D under a tag the chain does not list, and two
  revenue tags that agree on quarters and disagree on annuals.
* Becton Dickinson — fiscal year ending 30 September, revenue on a fallback tag.
* BioNTech — IFRS filer with nothing usable.
"""

from __future__ import annotations

import datetime as dt

import pytest

from transform.fundamentals import (
    Basis,
    build_quarterly_table,
    quarterly_series,
)

M = 1_000_000


def D(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def quarters(payload, concept):
    return quarterly_series(payload, concept).by_end()


# --------------------------------------------------------------------------- #
# Moderna — the straightforward case, checked against published results
# --------------------------------------------------------------------------- #


def test_moderna_2021_revenue_matches_reported_quarters(mrna):
    """Moderna reported $1,937M / $4,354M / $4,969M / $7,211M in 2021."""
    index = quarters(mrna, "revenue")

    assert index[D("2021-03-31")].val == pytest.approx(1_937 * M, abs=M)
    assert index[D("2021-06-30")].val == pytest.approx(4_354 * M, abs=M)
    assert index[D("2021-09-30")].val == pytest.approx(4_969 * M, abs=M)
    assert index[D("2021-12-31")].val == pytest.approx(7_211 * M, abs=M)


def test_moderna_q4_2021_is_derived_not_reported(mrna):
    """Q4 is almost never filed on its own — this is the annual minus nine months."""
    q4 = quarters(mrna, "revenue")[D("2021-12-31")]

    assert q4.basis is Basis.DERIVED
    assert q4.start == D("2021-10-01")
    assert q4.derived_from == ((D("2021-01-01"), D("2021-12-31")), (D("2021-01-01"), D("2021-09-30")))


def test_moderna_2021_quarters_sum_to_the_reported_year(mrna):
    """Moderna's FY2021 revenue was $18,471M."""
    ttm = quarterly_series(mrna, "revenue").trailing_twelve_months(D("2021-12-31"))

    assert ttm.val == pytest.approx(18_471 * M, abs=M)


def test_moderna_2022_revenue_matches_reported_year(mrna):
    """FY2022 revenue was $19,263M, with Q4 at $5,084M."""
    assert quarters(mrna, "revenue")[D("2022-12-31")].val == pytest.approx(5_084 * M, abs=M)
    assert quarterly_series(mrna, "revenue").trailing_twelve_months(D("2022-12-31")).val == pytest.approx(
        19_263 * M, abs=M
    )


def test_moderna_ttm_spans_a_tag_switch_that_was_proven_harmless(mrna):
    """Moderna moves tags partway through 2022, but the two agree where they overlap.

    Q1 and Q2 2022 come from `Revenues`, Q3 and Q4 from
    `RevenueFromContractWithCustomerExcludingAssessedTax`. Refusing every
    multi-tag window would throw away a correct year; the tags are allowed to be
    combined here because they match on every period the filer reports under
    both. Contrast `test_pfizer_revenue_chain_tags_diverge_on_annuals_only`.
    """
    series = quarterly_series(mrna, "revenue")
    window = [series.by_end()[D(e)] for e in ("2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31")]
    ttm = series.trailing_twelve_months(D("2022-12-31"))

    assert len({q.tag for q in window}) == 2
    assert series.divergences == ()
    assert frozenset(
        ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax")
    ) in series.interchangeable
    assert ttm.val == pytest.approx(19_263 * M, abs=M)
    assert len(ttm.contributing_tags) == 2


def test_pfizer_single_tag_ttm_is_computed_but_carries_a_flag(pfe):
    """Pfizer's 2023 window sits entirely on `Revenues`, so it is arithmetically sound.

    The Q4 in it was still derived from an annual the chain tags dispute, so the
    figure is produced and the series flag marks the uncertainty rather than the
    year being dropped. Only a window that *spans* tags is refused outright,
    because that additionally requires trusting that two tags mean the same thing.
    """
    series = quarterly_series(pfe, "revenue")
    ttm = series.trailing_twelve_months(D("2023-12-31"))

    assert ttm is not None
    assert ttm.contributing_tags == ("Revenues",)
    assert D("2023-12-31") in series.suspect_ends
    assert "revenue:chain_tags_diverge" in series.flags


def test_moderna_operating_cash_flow_is_entirely_year_to_date(mrna):
    """Only Q1 is reported directly; Q2-Q4 must all be differenced. FY2021 OCF was $13,620M."""
    index = quarters(mrna, "ocf")
    year = [index[D(e)] for e in ("2021-03-31", "2021-06-30", "2021-09-30", "2021-12-31")]

    assert [q.basis for q in year] == [Basis.REPORTED, Basis.DERIVED, Basis.DERIVED, Basis.DERIVED]
    assert sum(q.val for q in year) == pytest.approx(13_620 * M, abs=M)


def test_moderna_every_fiscal_year_reconciles(mrna):
    """No restatement skew here, so all four quarters must add back to each annual."""
    for concept in ("revenue", "rnd", "ocf"):
        series = quarterly_series(mrna, concept)
        assert series.reconciliations, f"{concept} produced no reconcilable year"
        assert all(r.ok for r in series.reconciliations), [
            r.to_dict() for r in series.reconciliations if not r.ok
        ]


# --------------------------------------------------------------------------- #
# Merck — published figures, and a restatement the algorithm cannot repair
# --------------------------------------------------------------------------- #


def test_merck_2023_revenue_matches_reported_figures(mrk):
    """Merck's FY2023 revenue was $60,115M, with Q4 at $14,630M."""
    index = quarters(mrk, "revenue")

    assert index[D("2023-03-31")].val == pytest.approx(14_487 * M, abs=M)
    assert index[D("2023-12-31")].val == pytest.approx(14_630 * M, abs=M)
    assert index[D("2023-12-31")].basis is Basis.DERIVED
    assert sum(
        index[D(e)].val for e in ("2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31")
    ) == pytest.approx(60_115 * M, abs=2 * M)


def test_merck_fy2020_fails_reconciliation(mrk):
    """FY2020 was restated for the Organon spin-off; the 2020 quarters were not.

    The quarters are still emitted — they are what Merck filed — but the year is
    flagged so nothing downstream treats the sum as a real total.
    """
    series = quarterly_series(mrk, "revenue")
    failures = {r.fiscal_year_end: r for r in series.reconciliations if not r.ok}

    assert D("2020-12-31") in failures
    assert failures[D("2020-12-31")].annual == pytest.approx(41_518 * M, abs=M)
    assert failures[D("2020-12-31")].quarters_sum == pytest.approx(43_287 * M, abs=M)
    assert "revenue:fy_reconciliation_failed" in series.flags


def test_merck_other_years_still_reconcile(mrk):
    """The flag must be specific to the restated year, not a blanket warning."""
    ok_years = {r.fiscal_year_end.year for r in quarterly_series(mrk, "revenue").reconciliations if r.ok}

    assert {2018, 2019, 2021, 2022, 2023} <= ok_years


# --------------------------------------------------------------------------- #
# Pfizer — 52/53-week calendar, a missing tag, and diverging chain entries
# --------------------------------------------------------------------------- #


def test_pfizer_quarter_ends_follow_a_52_53_week_calendar(pfe):
    """Quarter ends drift off month end, which the day-count windows must tolerate."""
    ends = sorted(e for e in quarters(pfe, "revenue") if e.year == 2022)

    assert ends == [D("2022-04-03"), D("2022-07-03"), D("2022-10-02"), D("2022-12-31")]


def test_pfizer_q3_2021_matches_the_reported_figure(pfe):
    """Pfizer reported $24,035M of revenue in Q3 2021."""
    assert quarters(pfe, "revenue")[D("2021-10-03")].val == pytest.approx(24_035 * M, abs=M)


def test_pfizer_rnd_does_not_resolve_under_the_spec_chain(pfe):
    """SPEC §5.1's R&D chain has one entry, and Pfizer does not use it.

    Pfizer tags R&D as `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost`.
    Widening the chain is a deliberate decision, not something this module should
    do implicitly, so R&D is empty and the near miss is named instead of the gap
    being passed off as "this company reports no R&D".
    """
    series = quarterly_series(pfe, "rnd")

    assert series.values == ()
    assert "rnd:no_tag_resolved" in series.flags
    assert series.resolution.near_miss_tags == (
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    )


def test_pfizer_revenue_chain_tags_diverge_on_annuals_only(pfe):
    """The two tags agree on every quarter and year-to-date period, and only differ on annuals."""
    divergences = quarterly_series(pfe, "revenue").divergences
    disputed = {(d.start, d.end) for d in divergences}

    assert disputed == {
        (D("2021-01-01"), D("2021-12-31")),
        (D("2022-01-01"), D("2022-12-31")),
        (D("2023-01-01"), D("2023-12-31")),
    }
    assert all((d.end - d.start).days > 300 for d in divergences)


def test_pfizer_q4s_derived_from_a_disputed_annual_are_flagged(pfe):
    """This is the number that would otherwise be quietly wrong.

    Q4 2022 comes out at $15,753M because the annual is tagged on the
    revenue-from-contracts basis while the nine-month figure under the same tag
    is the total. The same filing supports $25,135M under `Revenues`. The value
    is still emitted, but marked, because choosing between the two means guessing
    what the filer meant.
    """
    series = quarterly_series(pfe, "revenue")

    assert series.suspect_ends == {D("2021-12-31"), D("2022-12-31"), D("2023-12-31")}
    assert "revenue:chain_tags_diverge" in series.flags
    assert series.by_end()[D("2022-12-31")].val == pytest.approx(15_753 * M, abs=M)


def test_pfizer_flagged_quarters_are_visible_on_the_row(pfe):
    table = build_quarterly_table(pfe)
    row = {r.period_end: r for r in table.rows}[D("2022-12-31")]

    assert "revenue:tag_basis_uncertain" in row.flags


def test_pfizer_undisputed_quarters_are_not_flagged(pfe):
    """Only quarters whose derivation touched a disputed period may be marked."""
    table = build_quarterly_table(pfe)
    row = {r.period_end: r for r in table.rows}[D("2022-07-03")]

    assert "revenue:tag_basis_uncertain" not in row.flags


# --------------------------------------------------------------------------- #
# Becton Dickinson — a fiscal year that is not the calendar year
# --------------------------------------------------------------------------- #


def test_bdx_fiscal_year_2024_tiles_and_reconciles(bdx):
    """BD's FY2024 ran 1 October 2023 to 30 September 2024 and totalled $20,178M."""
    index = quarters(bdx, "revenue")
    year = [index[D(e)] for e in ("2023-12-31", "2024-03-31", "2024-06-30", "2024-09-30")]

    assert [q.val / M for q in year] == pytest.approx([4_706, 5_045, 4_990, 5_437], abs=1)
    assert sum(q.val for q in year) == pytest.approx(20_178 * M, abs=M)
    assert year[0].start == D("2023-10-01")


def test_bdx_fourth_quarter_falls_in_september(bdx):
    """The Q4 derivation must key off the filer's year end, not December."""
    q4 = quarters(bdx, "revenue")[D("2024-09-30")]

    assert q4.basis is Basis.DERIVED
    assert (q4.start, q4.end) == (D("2024-07-01"), D("2024-09-30"))


def test_bdx_revenue_uses_a_fallback_tag(bdx):
    """BD has no RevenueFromContractWithCustomer tag at all."""
    series = quarterly_series(bdx, "revenue")

    assert series.resolution.tags_used == ("Revenues",)
    assert series.resolution.uses_fallback
    assert "revenue:fallback_tag" in series.flags


def test_bdx_ocf_gap_where_a_quarter_would_need_cross_tag_arithmetic(bdx):
    """BD switched OCF tags mid-year, so one quarter cannot be derived at all.

    Q1 FY2026 is tagged `NetCashProvidedByUsedInOperatingActivities` while the
    half-year is tagged `...ContinuingOperations`. Differencing them would assume
    the two are the same measure. They are not — BD reports discontinued
    operations — so the quarter is left empty rather than filled with a number
    that looks right.
    """
    table = build_quarterly_table(bdx)
    row = {r.period_end: r for r in table.rows}[D("2026-03-31")]

    assert row.values["ocf"] is None
    assert row.values["revenue"] is not None  # the row itself survives
    assert quarterly_series(bdx, "ocf").trailing_twelve_months() is None


# --------------------------------------------------------------------------- #
# BioNTech — a filer M1 cannot cover
# --------------------------------------------------------------------------- #


def test_ifrs_filer_yields_nothing_and_says_why(bntx):
    """SPEC §10: this must be an empty, labelled result, not an exception."""
    table = build_quarterly_table(bntx)

    assert table.rows == ()
    assert table.taxonomies == ("ifrs-full", "us-gaap")
    assert "no_concepts_resolved" in table.flags
    assert all(f"{c}:no_tag_resolved" in table.flags for c in ("revenue", "rnd", "ocf"))


def test_ifrs_tag_with_a_colliding_local_name_is_not_used(bntx):
    """BioNTech has an `ifrs-full:ResearchAndDevelopmentExpense`; matching on tag
    name alone would silently pull IFRS figures into a us-gaap series."""
    assert "ResearchAndDevelopmentExpense" in bntx["facts"]["ifrs-full"]
    assert quarterly_series(bntx, "rnd").values == ()


def test_twenty_f_forms_are_excluded(bntx):
    """Every BioNTech fact is on a 20-F, which is not in the periodic form filter."""
    forms = {
        f["form"]
        for tags in bntx["facts"].values()
        for tag in tags.values()
        for facts in tag["units"].values()
        for f in facts
    }

    assert forms <= {"20-F", "20-F/A"}


# --------------------------------------------------------------------------- #
# Cross-company invariants
# --------------------------------------------------------------------------- #


@pytest.fixture(params=["pfe", "mrna", "bdx", "mrk"])
def real_payload(request):
    return request.getfixturevalue(request.param)


def test_quarters_are_plausible_lengths(real_payload):
    for concept in ("revenue", "rnd", "ocf"):
        for value in quarterly_series(real_payload, concept).values:
            assert 80 <= value.days <= 100, value.to_dict()


def test_quarters_never_overlap_within_a_concept(real_payload):
    """An overlap would mean double counting in any TTM built on top."""
    for concept in ("revenue", "rnd", "ocf"):
        values = quarterly_series(real_payload, concept).values
        for earlier, later in zip(values, values[1:]):
            assert earlier.end < later.start, (earlier.to_dict(), later.to_dict())


def test_derived_values_carry_their_sources(real_payload):
    """SPEC §6: every figure has to be traceable back to a filing."""
    for concept in ("revenue", "rnd", "ocf"):
        for value in quarterly_series(real_payload, concept).values:
            assert value.accns
            assert value.tag
            if value.basis is Basis.DERIVED:
                assert len(value.derived_from) == 2
                assert len(value.accns) == 2
            else:
                assert value.derived_from == ()


def test_table_is_json_serialisable(real_payload):
    import json

    payload = build_quarterly_table(real_payload).to_dict()

    assert json.loads(json.dumps(payload))["quarterly"]
