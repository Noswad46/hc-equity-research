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


def test_moderna_2022_now_resolves_to_a_single_tag(mrna):
    """Largest-wins removed a tag switch that used to sit inside FY2022.

    Both tags cover Q3 and Q4 2022 with identical values, so chain order used to
    hand those quarters to the contracts-with-customers tag while Q1 and Q2 came
    from `Revenues`. The year is now uniformly on `Revenues` and totals the same
    $19,263M, which is what Moderna reported.
    """
    series = quarterly_series(mrna, "revenue")
    window = [series.by_end()[D(e)] for e in ("2022-03-31", "2022-06-30", "2022-09-30", "2022-12-31")]
    ttm = series.trailing_twelve_months(D("2022-12-31"))

    assert {q.tag for q in window} == {"Revenues"}
    assert ttm.val == pytest.approx(19_263 * M, abs=M)
    assert ttm.contributing_tags == ("Revenues",)


def test_moderna_still_switches_tags_where_it_has_no_choice(mrna):
    """Moderna stops tagging `Revenues` after 2022, so 2023 onward has one candidate."""
    series = quarterly_series(mrna, "revenue")
    spans = series.tag_spans

    assert spans["Revenues"][1] == D("2022-12-31")
    assert spans["RevenueFromContractWithCustomerExcludingAssessedTax"][0] == D("2023-03-31")
    assert "revenue:mixed_tags" in series.flags


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


def test_pfizer_rnd_resolves_on_the_excluding_iprd_basis(pfe):
    """Pfizer reports R&D excluding acquired IPR&D, and now produces a full series.

    The tag is not an alternative spelling of `ResearchAndDevelopmentExpense` —
    Moderna's version of that tag includes acquired IPR&D — so the basis is
    recorded on every value and left un-normalised.
    """
    series = quarterly_series(pfe, "rnd")

    assert len(series.values) >= 30
    assert series.resolution.tags_used == (
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    )
    assert series.measurement_bases == ("rnd_excluding_acquired_iprd",)
    assert all(v.measurement_basis == "rnd_excluding_acquired_iprd" for v in series.values)
    assert "rnd:no_tag_resolved" not in series.flags


def test_pfizer_rnd_quarters_are_contiguous(pfe):
    """The fixture covers 2018 onward, where Pfizer's R&D series has no holes."""
    values = quarterly_series(pfe, "rnd").values

    for earlier, later in zip(values, values[1:]):
        assert (later.start - earlier.end).days == 1, (earlier.end, later.start)


def test_pfizer_rnd_ttm_is_plausible(pfe):
    """Pfizer's trailing R&D runs around $11bn on the excluding-IPR&D basis."""
    ttm = quarterly_series(pfe, "rnd").trailing_twelve_months()

    assert 9_000 * M < ttm.val < 13_000 * M
    assert ttm.measurement_basis == "rnd_excluding_acquired_iprd"


def test_moderna_rnd_uses_the_including_iprd_basis(mrna):
    """The counterpart case: the same concept, the other basis, on the same run."""
    series = quarterly_series(mrna, "rnd")

    assert series.resolution.tags_used == ("ResearchAndDevelopmentExpense",)
    assert series.measurement_bases == ("rnd_including_acquired_iprd",)


def test_the_two_rnd_bases_are_recorded_never_reconciled(pfe, mrna):
    """Comparing these two directly is not valid, and nothing here pretends otherwise."""
    pfizer = quarterly_series(pfe, "rnd").values[-1]
    moderna = quarterly_series(mrna, "rnd").values[-1]

    assert pfizer.measurement_basis != moderna.measurement_basis
    # No normalisation factor, adjustment or blending exists on either value.
    assert pfizer.contributing_bases == ("rnd_excluding_acquired_iprd",)
    assert moderna.contributing_bases == ("rnd_including_acquired_iprd",)


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


def test_pfizer_q4_2022_now_resolves_to_the_revenues_basis(pfe):
    """The $9bn error, corrected by the selection rule.

    Both candidates cover Q4 2022 and both reconcile within their own tag, so the
    larger wins: $25,135M on `Revenues` rather than $15,753M on the
    contracts-with-customers component. The component figure was never wrong
    arithmetic — it was the wrong measure presented as the total.
    """
    q4 = quarterly_series(pfe, "revenue").by_end()[D("2022-12-31")]

    assert q4.val == pytest.approx(25_135 * M, abs=M)
    assert q4.tag == "Revenues"
    assert q4.measurement_basis == "revenue_total"


def test_pfizer_q4_2023_is_on_the_revenues_basis(pfe):
    q4 = quarterly_series(pfe, "revenue").by_end()[D("2023-12-31")]

    assert q4.val == pytest.approx(14_569 * M, abs=M)
    assert q4.tag == "Revenues"


def test_pfizer_q4_2021_stays_on_the_component_basis_and_says_so(pfe):
    """The one Q4 the selection rule cannot move, because there is nothing to move to.

    Under `Revenues` Pfizer filed only the FY2021 annual — no year-to-date facts
    for 2021 at all — so no Q4 2021 candidate exists on that basis. Producing one
    would mean subtracting the contracts-with-customers nine-month figure from
    the `Revenues` annual, and that cross-tag subtraction is exactly what
    produced the $9bn error in the first place. A flagged figure on a known basis
    beats a clean-looking figure built from two different ones.
    """
    series = quarterly_series(pfe, "revenue")
    q4 = series.by_end()[D("2021-12-31")]

    assert q4.tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert q4.val == pytest.approx(16_186 * M, abs=M)
    assert "tag_basis_uncertain" in q4.flags
    assert "revenue:chain_tags_diverge" in series.flags


def test_pfizer_divergence_detection_survives_the_selection_rule(pfe):
    """Selecting correctly is not a reason to stop reporting the disagreement."""
    divergences = quarterly_series(pfe, "revenue").divergences
    disputed = {(d.start, d.end) for d in divergences}

    assert disputed == {
        (D("2021-01-01"), D("2021-12-31")),
        (D("2022-01-01"), D("2022-12-31")),
        (D("2023-01-01"), D("2023-12-31")),
    }


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
# Johnson & Johnson — the other filer the one-entry R&D chain lost
# --------------------------------------------------------------------------- #


def test_jnj_rnd_produces_a_complete_quarterly_series(jnj):
    """J&J tags quarterly R&D only under the excluding-IPR&D name.

    `ResearchAndDevelopmentExpense` does exist for J&J, but carries annual
    figures alone — nine facts, all 10-K — so the single-entry chain yielded no
    quarters whatsoever.
    """
    series = quarterly_series(jnj, "rnd")

    assert len(series.values) >= 30
    assert series.resolution.tags_used == (
        "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
    )
    assert "rnd:no_quarters_derived" not in series.flags
    assert "rnd:no_tag_resolved" not in series.flags


def test_jnj_rnd_quarters_are_contiguous(jnj):
    """A complete series means no holes, not just a non-empty one."""
    values = quarterly_series(jnj, "rnd").values

    for earlier, later in zip(values, values[1:]):
        assert (later.start - earlier.end).days == 1, (earlier.end, later.start)


def test_jnj_rnd_ttm_is_plausible(jnj):
    """J&J's trailing R&D runs around $15bn."""
    ttm = quarterly_series(jnj, "rnd").trailing_twelve_months()

    assert 12_000 * M < ttm.val < 18_000 * M
    assert ttm.measurement_basis == "rnd_excluding_acquired_iprd"


def test_jnj_annual_only_tag_contributes_no_quarters(jnj):
    """The including-IPR&D tag has annuals but no year-to-date facts to difference."""
    from transform.fundamentals import discrete_quarters, extract_facts

    facts = extract_facts(jnj, "ResearchAndDevelopmentExpense")

    assert facts  # the tag is present
    assert discrete_quarters(facts) == {}  # but yields nothing


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


def test_bdx_revenue_sits_on_the_primary_tag(bdx):
    """BD has no RevenueFromContractWithCustomer tag at all, and `Revenues` is now primary."""
    series = quarterly_series(bdx, "revenue")

    assert series.resolution.tags_used == ("Revenues",)
    assert not series.resolution.uses_fallback
    assert "revenue:fallback_tag" not in series.flags
    assert "revenue:mixed_tags" not in series.flags


def test_bdx_revenue_figures_are_unchanged_by_the_selection_rule(bdx):
    """BD's candidates never overlap, so largest-wins has nothing to change here."""
    index = quarterly_series(bdx, "revenue").by_end()

    assert index[D("2024-09-30")].val == pytest.approx(5_437 * M, abs=M)
    assert index[D("2024-09-30")].basis is Basis.DERIVED
    assert index[D("2023-12-31")].start == D("2023-10-01")


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


@pytest.fixture(params=["pfe", "mrna", "bdx", "mrk", "jnj"])
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


def test_every_value_declares_its_measurement_basis(real_payload):
    """All three M1 concepts have tags that measure different things."""
    for concept in ("revenue", "rnd", "ocf"):
        for value in quarterly_series(real_payload, concept).values:
            assert value.measurement_basis is not None, value.to_dict()


def test_arithmetic_never_crosses_tags(real_payload):
    """The rule that kept the Pfizer revenue error to one flagged quarter.

    A derived value subtracts two year-to-date periods; both must come from the
    tag the value is attributed to. Selection happens after derivation, never
    inside it.
    """
    for concept in ("revenue", "rnd", "ocf"):
        series = quarterly_series(real_payload, concept)
        for value in series.values:
            if value.basis is Basis.DERIVED:
                assert value.contributing_tags == (value.tag,)
                assert len(set(value.contributing_bases)) == 1


def test_table_is_json_serialisable(real_payload):
    import json

    payload = build_quarterly_table(real_payload).to_dict()

    assert json.loads(json.dumps(payload))["quarterly"]
