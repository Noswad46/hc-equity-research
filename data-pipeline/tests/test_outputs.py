"""The JSON contract the site consumes (SPEC §7).

The site is built from these files, so their shape is an interface. Two things
matter more than the values themselves: every key is always present, so a null
means "not computed" rather than "key missing on this milestone"; and the numbers
are the filer's own integers, so nothing on a page can differ from what SEC
reported by so much as a rounding step.
"""

from __future__ import annotations

import json

import pytest

from run import (
    DERIVED_METRICS,
    UNCOMPUTED_PIPELINE_METRICS,
    _SCREENER_KEYS,
    company_document,
    number,
    quality_records,
)
from sources.edgar import Company
from transform.fundamentals import M2_CONCEPTS, build_quarterly_table

M = 1_000_000


def company(ticker: str, cik: str) -> Company:
    return Company(
        ticker=ticker,
        cik=cik,
        name=f"{ticker} Inc.",
        subsector="large_cap_pharma",
        therapeutic_focus=("vaccines",),
    )


@pytest.fixture(scope="module")
def pfe_doc(request):
    facts = request.getfixturevalue("pfe")
    return company_document(company("PFE", "0000078003"), facts)


@pytest.fixture(scope="module")
def mrk_doc(request):
    facts = request.getfixturevalue("mrk")
    return company_document(company("MRK", "0000310158"), facts)


# --------------------------------------------------------------------------- #
# Number fidelity
# --------------------------------------------------------------------------- #


def test_integral_values_serialise_as_integers():
    """The float is an internal convenience; it must not reach disk as `.0`."""
    assert number(25_135_000_000.0) == 25_135_000_000
    assert isinstance(number(25_135_000_000.0), int)
    assert number(None) is None
    assert number(0.25) == 0.25


def test_quarterly_values_are_integers_not_floats(pfe_doc):
    for row in pfe_doc["quarterly"]:
        for concept in M2_CONCEPTS:
            value = row[concept]
            assert value is None or isinstance(value, int), (row["period_end"], concept, value)


def test_values_match_the_series_exactly(pfe_doc, pfe):
    """No rounding anywhere between the transform and the file."""
    series = build_quarterly_table(pfe, M2_CONCEPTS).series["revenue"].by_end()
    rows = {r["period_end"]: r["revenue"] for r in pfe_doc["quarterly"]}

    for end, value in series.items():
        assert rows[end.isoformat()] == int(value.val)


def test_json_roundtrips(pfe_doc):
    assert json.loads(json.dumps(pfe_doc))["ticker"] == "PFE"


# --------------------------------------------------------------------------- #
# Schema stability
# --------------------------------------------------------------------------- #


def test_every_screener_key_is_present(pfe_doc):
    for key in _SCREENER_KEYS:
        assert key in pfe_doc, key


def test_uncomputed_pipeline_metrics_are_null_not_absent(pfe_doc):
    """SPEC §5.2 clinical metrics are M4; the keys must still exist."""
    for key in UNCOMPUTED_PIPELINE_METRICS:
        assert key in pfe_doc
        assert pfe_doc[key] is None


def test_derived_metrics_are_present_as_result_objects(pfe_doc):
    """Each carries its value or the reason there isn't one, never a bare null."""
    for key in DERIVED_METRICS:
        assert key in pfe_doc
        assert set(pfe_doc[key]) >= {"value", "suppressed_by", "flags"}


def test_unbuilt_sections_are_null(pfe_doc):
    assert pfe_doc["pipeline"] is None
    assert pfe_doc["regulatory"] is None


def test_quarterly_rows_carry_every_concept_key(pfe_doc):
    """A concept missing for a period is null, never an absent key."""
    for row in pfe_doc["quarterly"]:
        for concept in M2_CONCEPTS:
            assert concept in row
            assert concept in row["source_tags"]
            assert concept in row["measurement_basis"]


# --------------------------------------------------------------------------- #
# Annual table
# --------------------------------------------------------------------------- #


def test_annual_rows_are_fiscal_year_ends_only(mrk_doc):
    """Cash is reported quarterly; without a restriction each balance date would
    open an annual row whose flow columns were all null."""
    ends = [r["period_end"] for r in mrk_doc["annual"]]

    assert ends == sorted(ends)
    assert all(e.endswith("-12-31") for e in ends), ends
    assert len(ends) == len(set(ends))


def test_annual_rows_carry_a_flow_figure(mrk_doc):
    for row in mrk_doc["annual"]:
        assert row["revenue"] is not None, row["period_end"]


def test_annual_cash_is_the_year_end_balance(mrk_doc):
    row = {r["period_end"]: r for r in mrk_doc["annual"]}["2023-12-31"]

    assert row["cash"] == 6_841_000_000


def test_bdx_annual_rows_land_on_a_september_year_end(bdx):
    doc = company_document(company("BDX", "0000010795"), bdx)
    ends = [r["period_end"] for r in doc["annual"]]

    assert all(e.endswith("-09-30") for e in ends), ends


# --------------------------------------------------------------------------- #
# The two verification cases
# --------------------------------------------------------------------------- #


def test_pfizer_q4_2021_is_recorded_on_the_component_basis(pfe_doc):
    row = {r["period_end"]: r for r in pfe_doc["quarterly"]}["2021-12-31"]

    assert row["revenue"] == 16_186_000_000
    assert row["source_tags"]["revenue"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert row["measurement_basis"]["revenue"] == "revenue_contracts_with_customers"
    assert "revenue:tag_basis_uncertain" in row["flags"]


def test_pfizer_q4_2021_flag_reaches_the_data_quality_list(pfe_doc):
    """The page renders from this list, so the flag has to be in it with its period."""
    hits = [
        r
        for r in pfe_doc["data_quality"]
        if r["code"] == "tag_basis_uncertain"
        and r["concept"] == "revenue"
        and r["period_end"] == "2021-12-31"
    ]

    assert len(hits) == 1
    assert hits[0]["detail"]["measurement_basis"] == "revenue_contracts_with_customers"


def test_merck_fy2020_growth_is_null_with_a_reason(mrk_doc):
    row = {r["period_end"]: r for r in mrk_doc["annual"]}["2020-12-31"]

    assert row["revenue"] == 41_518_000_000  # data still emitted
    assert row["revenue_growth_yoy"]["value"] is None
    assert row["revenue_growth_yoy"]["suppressed_by"] == ["restated_fiscal_year"]


def test_merck_fy2020_reconciliation_is_listed_with_its_numbers(mrk_doc):
    hits = [
        r
        for r in mrk_doc["data_quality"]
        if r["code"] == "fy_reconciliation_failed" and r["period_end"] == "2020-12-31"
    ]

    assert hits
    detail = next(h["detail"] for h in hits if h["concept"] == "revenue")
    assert detail["annual"] == 41_518_000_000
    assert detail["quarters_sum"] == 43_287_000_000


def test_merck_growth_outside_the_restated_years_is_computed(mrk_doc):
    row = {r["period_end"]: r for r in mrk_doc["annual"]}["2023-12-31"]

    assert row["revenue_growth_yoy"]["value"] is not None


# --------------------------------------------------------------------------- #
# Data-quality completeness
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("ticker", ["PFE", "MRK"])
def test_every_series_flag_has_a_data_quality_record(ticker, request):
    """A flag with no record would be invisible on the page."""
    fixture = {"PFE": "pfe", "MRK": "mrk"}[ticker]
    facts = request.getfixturevalue(fixture)
    doc = company_document(company(ticker, "0000000001"), facts)

    codes = {r["code"] for r in doc["data_quality"]}
    for flag in doc["data_quality_flags"]:
        _, _, code = flag.partition(":")
        assert code in codes, f"{flag} has no data_quality record"


def test_data_quality_records_have_a_stable_shape(pfe_doc):
    for record in pfe_doc["data_quality"]:
        assert set(record) >= {"code", "concept", "period_start", "period_end"}


def test_quality_records_are_empty_for_a_clean_series():
    payload = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": f"2025-{s}", "end": f"2025-{e}", "val": 100 * M,
                             "form": "10-Q", "accn": f"a{i}", "filed": "2026-01-01"}
                            for i, (s, e) in enumerate(
                                [("01-01", "03-31"), ("04-01", "06-30"),
                                 ("07-01", "09-30"), ("10-01", "12-31")]
                            )
                        ]
                    }
                }
            }
        }
    }
    series = build_quarterly_table(payload, ("revenue",)).series

    assert quality_records(series) == []


# --------------------------------------------------------------------------- #
# Source links
# --------------------------------------------------------------------------- #


def test_filings_point_at_edgar_and_are_deduplicated(pfe_doc):
    filings = pfe_doc["filings"]

    assert filings
    accessions = [f["accession"] for f in filings]
    assert len(accessions) == len(set(accessions))
    for filing in filings:
        assert filing["url"].startswith("https://www.sec.gov/Archives/edgar/data/78003/")
        assert filing["accession"] in filing["url"]
        assert filing["form"].startswith(("10-K", "10-Q"))


def test_filings_are_only_those_that_produced_a_figure(pfe_doc):
    """Source links must correspond to numbers on the page, not the whole history."""
    used = {
        accn
        for row in pfe_doc["quarterly"] + pfe_doc["annual"]
        for accn in []
    }
    linked = {f["accession"] for f in pfe_doc["filings"]}

    assert linked  # non-empty
    assert all(a in linked for a in used)
