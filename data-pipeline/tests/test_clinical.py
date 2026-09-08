"""Clinical pipeline: sponsor matching, aggregation and metrics.

The exclusion tests are the important ones. Merck & Co and Merck KGaA of
Darmstadt are unrelated listed companies that share a name, and putting a
competitor's 254 trials into Merck's pipeline is the single most damaging error
available in this part of the system — it would inflate every pipeline metric
and look entirely plausible while doing it. Those tests assert a raise, not a
warning.
"""

from __future__ import annotations

import datetime as dt

import pytest

from sources.clinicaltrials import (
    ClinicalTrialsClient,
    ClinicalTrialsError,
    EmptyPipelineError,
    Study,
    exact_sponsor_filter,
    read_study,
)
from sources.edgar import load_universe
from transform.clinical import (
    ACTIVE_STATUSES,
    DEPTH_WEIGHTS,
    DISCONTINUATION_MIN_TRIALS,
    clinical_momentum,
    discontinuation_rate,
    phase_of,
    pipeline_concentration,
    pipeline_depth_score,
    summarise,
)

AS_OF = dt.date(2026, 9, 1)

MERCK_KGAA = "Merck KGaA, Darmstadt, Germany"
EMD_SERONO = "EMD Serono Research & Development Institute, Inc."


def study(
    nct: str,
    *,
    sponsor: str = "Merck Sharp & Dohme LLC",
    status: str = "RECRUITING",
    phases: tuple[str, ...] = ("PHASE3",),
    conditions: tuple[str, ...] = ("Melanoma",),
    start: str | None = "2026-01-01",
    primary_completion: str | None = None,
) -> Study:
    return Study(
        nct_id=nct,
        title=f"Study {nct}",
        lead_sponsor=sponsor,
        status=status,
        phases=phases,
        conditions=conditions,
        enrollment=100,
        start=dt.date.fromisoformat(start) if start else None,
        primary_completion=dt.date.fromisoformat(primary_completion) if primary_completion else None,
        completion=None,
        why_stopped=None,
    )


class FakeClient(ClinicalTrialsClient):
    """Returns scripted studies per sponsor string, without touching the network."""

    def __init__(self, by_sponsor):
        super().__init__(cache_dir=None, sleep=lambda _: None)
        self._by_sponsor = by_sponsor

    def studies_for_sponsor(self, sponsor, *, refresh=False):  # type: ignore[override]
        return list(self._by_sponsor.get(sponsor, []))


# --------------------------------------------------------------------------- #
# Sponsor matching
# --------------------------------------------------------------------------- #


def test_sponsor_filter_is_a_whole_field_match():
    """Without FullMatch the same query also returns sponsors merely containing
    the tokens — 113 studies for Moderna rather than the 99 it leads."""
    built = exact_sponsor_filter("ModernaTX, Inc.")

    assert 'AREA[LeadSponsorName]COVERAGE[FullMatch]"ModernaTX, Inc."' in built
    assert "AREA[StudyType]INTERVENTIONAL" in built


def test_sponsor_filter_escapes_quotes():
    assert '\\"' in exact_sponsor_filter('Odd "Quoted" Sponsor')


# --------------------------------------------------------------------------- #
# Merck KGaA must never enter MRK
# --------------------------------------------------------------------------- #


def test_an_excluded_sponsor_in_a_result_raises():
    """A hard failure, not a filtered-out warning.

    If a query ever returns a study led by an excluded sponsor, the mapping is
    wrong and the run must stop rather than quietly emit a contaminated record.
    """
    client = FakeClient(
        {"Merck Sharp & Dohme LLC": [study("NCT1"), study("NCT2", sponsor=MERCK_KGAA)]}
    )

    with pytest.raises(ClinicalTrialsError, match="exclusion list"):
        client.studies_for_company(
            ["Merck Sharp & Dohme LLC"], exclusions=[MERCK_KGAA], ticker="MRK"
        )


def test_a_string_cannot_be_both_included_and_excluded():
    client = FakeClient({})

    with pytest.raises(ClinicalTrialsError, match="both included and excluded"):
        client.studies_for_company([MERCK_KGAA], exclusions=[MERCK_KGAA], ticker="MRK")


def test_clean_results_pass_the_exclusion_check():
    client = FakeClient({"Merck Sharp & Dohme LLC": [study("NCT1"), study("NCT2")]})
    out = client.studies_for_company(
        ["Merck Sharp & Dohme LLC"], exclusions=[MERCK_KGAA, EMD_SERONO], ticker="MRK"
    )

    assert [s.nct_id for s in out] == ["NCT1", "NCT2"]


def test_merck_universe_entry_excludes_the_german_company(pipeline_root):
    """The mapping itself, as configured, not just the machinery that enforces it."""
    mrk = next(c for c in load_universe(pipeline_root / "universe.yaml") if c.ticker == "MRK")

    assert MERCK_KGAA in mrk.ct_sponsor_exclusions
    assert EMD_SERONO in mrk.ct_sponsor_exclusions
    assert any("Merck Healthcare KGaA" in s for s in mrk.ct_sponsor_exclusions)
    assert any("SpringWorks" in s for s in mrk.ct_sponsor_exclusions)
    assert not any("KGaA" in s for s in mrk.ct_sponsor_names)


def test_divestitures_are_excluded_from_both_filers(pipeline_root):
    """The clinical perimeter has to match the financial reporting perimeter."""
    universe = {c.ticker: c for c in load_universe(pipeline_root / "universe.yaml")}

    assert "Organon and Co" in universe["MRK"].ct_sponsor_exclusions
    assert any("Viatris" in s for s in universe["PFE"].ct_sponsor_exclusions)
    assert not any("Organon" in s for s in universe["MRK"].ct_sponsor_names)
    assert not any("Viatris" in s for s in universe["PFE"].ct_sponsor_names)


# --------------------------------------------------------------------------- #
# A silent zero is an error
# --------------------------------------------------------------------------- #


def test_no_trials_for_a_configured_company_raises():
    """The Moderna trap at scale: at sixty tickers nobody notices an empty record."""
    client = FakeClient({})

    with pytest.raises(EmptyPipelineError, match="no interventional studies"):
        client.studies_for_company(["ModernaTX, Inc."], ticker="MRNA")


def test_no_sponsors_configured_is_not_an_error():
    """A company with no mapping yet is a gap, not a broken mapping."""
    assert FakeClient({}).studies_for_company([], ticker="XXX") == []


def test_studies_are_deduplicated_across_sponsor_strings():
    shared = study("NCT1")
    client = FakeClient({"A": [shared], "B": [shared, study("NCT2")]})

    assert len(client.studies_for_company(["A", "B"])) == 2


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_partial_dates_are_read_rather_than_discarded():
    """A third of start dates are month-only; dropping them would corrupt every
    trailing-twelve-month count."""
    parsed = read_study(
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT9", "briefTitle": "T"},
                "statusModule": {"overallStatus": "RECRUITING", "startDateStruct": {"date": "2024-06"}},
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "S"}},
                "designModule": {"phases": ["PHASE2"], "enrollmentInfo": {"count": 40}},
                "conditionsModule": {"conditions": ["X"]},
            }
        }
    )

    assert parsed.start == dt.date(2024, 6, 1)
    assert parsed.start_precision == "month"


def test_a_study_without_an_nct_id_is_skipped():
    assert read_study({"protocolSection": {"identificationModule": {}}}) is None


# --------------------------------------------------------------------------- #
# Phase assignment
# --------------------------------------------------------------------------- #


def test_a_phase_1_2_study_counts_once_at_its_highest_phase():
    """Counting it twice inflates depth; counting it as Phase 1 understates it."""
    assert phase_of(study("N", phases=("PHASE1", "PHASE2"))) == "PHASE2"


def test_a_device_trial_with_no_phase_is_not_applicable():
    assert phase_of(study("N", phases=())) == "NA"


# --------------------------------------------------------------------------- #
# Aggregation and metrics
# --------------------------------------------------------------------------- #


def test_only_active_statuses_count_as_active():
    studies = [
        study("A", status="RECRUITING"),
        study("B", status="ACTIVE_NOT_RECRUITING"),
        study("C", status="COMPLETED"),
        study("D", status="TERMINATED"),
    ]
    summary = summarise(studies, as_of=AS_OF)

    assert summary.active_trials_total == 2
    assert summary.total_trials == 4
    assert "COMPLETED" not in ACTIVE_STATUSES


def test_depth_score_applies_the_published_weights():
    studies = [
        study("A", phases=("PHASE1",)),
        study("B", phases=("PHASE2",)),
        study("C", phases=("PHASE3",)),
        study("D", phases=("PHASE4",)),
    ]
    result = pipeline_depth_score(summarise(studies, as_of=AS_OF))

    assert result.value == 1 + 3 + 8 + 12
    assert DEPTH_WEIGHTS == {"PHASE1": 1, "PHASE2": 3, "PHASE3": 8, "PHASE4": 12}


def test_concentration_is_one_when_every_trial_shares_a_condition():
    studies = [study(f"N{i}", conditions=("Melanoma",)) for i in range(5)]

    assert pipeline_concentration(studies).value == pytest.approx(1.0)


def test_concentration_falls_as_areas_spread():
    studies = [study(f"N{i}", conditions=(c,)) for i, c in enumerate("ABCD")]

    assert pipeline_concentration(studies).value == pytest.approx(0.25)


def test_a_multi_condition_trial_is_split_not_multiplied():
    """One broad trial must not count as several narrow ones."""
    one_broad = pipeline_concentration([study("N", conditions=("A", "B", "C", "D"))])

    assert one_broad.value == pytest.approx(0.25)


def test_momentum_is_the_difference_between_two_years():
    studies = [study(f"N{i}", start="2026-03-01") for i in range(5)] + [
        study(f"P{i}", start="2025-03-01") for i in range(2)
    ]
    summary = summarise(studies, as_of=AS_OF)

    assert summary.started_ttm == 5
    assert summary.started_prior_ttm == 2
    assert clinical_momentum(summary).value == 3.0


def test_discontinuation_rate_is_suppressed_on_a_small_sample():
    studies = [study("A", status="TERMINATED"), study("B", status="COMPLETED")]
    result = discontinuation_rate(summarise(studies, as_of=AS_OF))

    assert result.value is None
    assert result.suppressed_by == ("too_few_resolved_trials",)


def test_discontinuation_rate_is_reported_above_the_threshold():
    studies = [study(f"T{i}", status="TERMINATED") for i in range(3)] + [
        study(f"C{i}", status="COMPLETED") for i in range(9)
    ]
    summary = summarise(studies, as_of=AS_OF)
    result = discontinuation_rate(summary)

    assert summary.completed_all_time + summary.discontinued_all_time >= DISCONTINUATION_MIN_TRIALS
    assert result.value == pytest.approx(3 / 12)


def test_upcoming_readouts_exclude_dates_already_passed():
    studies = [
        study("PAST", primary_completion="2025-01-01"),
        study("SOON", primary_completion="2026-12-01"),
    ]
    summary = summarise(studies, as_of=AS_OF)

    assert [r["nct_id"] for r in summary.upcoming_readouts] == ["SOON"]
