"""Clinical pipeline aggregation and metrics (SPEC §5.2, §6, §7).

Turns a company's interventional studies into the `pipeline` object of SPEC §7
and the pipeline metrics of SPEC §6. The metric weights are published on the
methodology page; none of this is presented as proprietary.

Two things here need stating rather than assuming.

**"Active" is a definition, not an observation.** ClinicalTrials.gov has some
thirty overall statuses. Which of them count as an active programme decides every
metric downstream, so the set is named explicitly in `ACTIVE_STATUSES` rather
than inferred from a substring.

**Trial counts and financial figures are as-of different dates.** The registry is
updated continuously; SEC facts arrive quarterly. Any metric spanning both — R&D
per late-stage programme — must therefore carry the size of that gap, because it
is a ratio of two numbers that were never true at the same instant.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from sources.clinicaltrials import Study
from transform.fundamentals import MetricResult, PeriodValue, QuarterlySeries, guard_metric

__all__ = [
    "is_active",
    "ACTIVE_STATUSES",
    "DEPTH_WEIGHTS",
    "DISCONTINUATION_MIN_TRIALS",
    "Pipeline",
    "clinical_momentum",
    "discontinuation_rate",
    "phase_of",
    "pipeline_concentration",
    "pipeline_depth_score",
    "rnd_per_late_stage_programme",
    "summarise",
]

#: Statuses that count as an active programme. Named rather than pattern-matched:
#: `ACTIVE_NOT_RECRUITING` and `NOT_YET_RECRUITING` both contain "RECRUITING" and
#: mean different things, and `TERMINATED` and `COMPLETED` are both finished but
#: only one is a failure.
ACTIVE_STATUSES = frozenset(
    {"RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION", "NOT_YET_RECRUITING"}
)

#: A trial that stopped early. `WITHDRAWN` never enrolled a patient; `TERMINATED`
#: and `SUSPENDED` stopped after starting.
DISCONTINUED_STATUSES = frozenset({"TERMINATED", "WITHDRAWN", "SUSPENDED"})

COMPLETED_STATUSES = frozenset({"COMPLETED"})

#: SPEC §6: 1×Ph1 + 3×Ph2 + 8×Ph3 + 12×Ph4/registration. A transparent heuristic,
#: published on the methodology page. Weights rise steeply because a Phase 3
#: programme represents far more committed capital and far more of the value than
#: a Phase 1, not because later trials are more numerous.
DEPTH_WEIGHTS: Mapping[str, int] = {"PHASE1": 1, "PHASE2": 3, "PHASE3": 8, "PHASE4": 12}

#: SPEC §6: a discontinuation rate over a handful of trials is noise.
DISCONTINUATION_MIN_TRIALS = 10

#: Late stage, for R&D per programme.
LATE_STAGE = frozenset({"PHASE2", "PHASE3"})

_PHASE_LABELS = {
    "EARLY_PHASE1": "early_phase_1",
    "PHASE1": "phase_1",
    "PHASE2": "phase_2",
    "PHASE3": "phase_3",
    "PHASE4": "phase_4",
    "NA": "not_applicable",
}


def phase_of(study: Study) -> str:
    """The single phase a study counts as.

    A study may declare several — `["PHASE1", "PHASE2"]` is common for a
    dose-escalation that rolls into expansion. It counts once, at the highest
    phase it reaches, so a Phase 1/2 is not double-counted and is not written
    down to Phase 1.
    """
    if not study.phases:
        return "NA"
    order = ["EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"]
    ranked = [p for p in study.phases if p in order]
    if not ranked:
        return "NA"
    return max(ranked, key=order.index)


def is_active(study: Study) -> bool:
    return (study.status or "") in ACTIVE_STATUSES


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Pipeline:
    """The SPEC §7 `pipeline` object, plus the inputs its metrics were built from."""

    as_of: dt.date
    total_trials: int
    active_trials_total: int
    by_phase: Mapping[str, int]
    by_status: Mapping[str, int]
    top_conditions: tuple[Mapping[str, Any], ...]
    upcoming_readouts: tuple[Mapping[str, Any], ...]
    started_ttm: int
    started_prior_ttm: int
    discontinued_all_time: int
    completed_all_time: int
    active_late_stage: int
    sponsors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "sponsors": list(self.sponsors),
            "total_trials": self.total_trials,
            "active_trials_total": self.active_trials_total,
            "by_phase": dict(self.by_phase),
            "by_status": dict(self.by_status),
            "top_conditions": [dict(c) for c in self.top_conditions],
            "upcoming_readouts": [dict(r) for r in self.upcoming_readouts],
            "started_ttm": self.started_ttm,
            "started_prior_ttm": self.started_prior_ttm,
            "discontinued_all_time": self.discontinued_all_time,
            "completed_all_time": self.completed_all_time,
            "active_late_stage": self.active_late_stage,
        }


def summarise(
    studies: Sequence[Study],
    *,
    as_of: dt.date,
    sponsors: Sequence[str] = (),
    top_conditions: int = 10,
    upcoming: int = 10,
) -> Pipeline:
    """Aggregate one company's studies into the SPEC §7 shape."""
    active = [s for s in studies if is_active(s)]

    by_phase = Counter(_PHASE_LABELS.get(phase_of(s), "not_applicable") for s in active)
    for label in ("phase_1", "phase_2", "phase_3", "phase_4", "not_applicable"):
        by_phase.setdefault(label, 0)

    by_status = Counter((s.status or "UNKNOWN").lower() for s in active)

    conditions = Counter(c for s in active for c in s.conditions)

    year_ago = as_of - dt.timedelta(days=365)
    two_years_ago = as_of - dt.timedelta(days=730)
    started_ttm = sum(1 for s in studies if s.start and year_ago < s.start <= as_of)
    started_prior = sum(1 for s in studies if s.start and two_years_ago < s.start <= year_ago)

    readouts = sorted(
        (s for s in active if s.primary_completion and s.primary_completion >= as_of),
        key=lambda s: s.primary_completion,  # type: ignore[arg-type,return-value]
    )[:upcoming]

    return Pipeline(
        as_of=as_of,
        sponsors=tuple(sponsors),
        total_trials=len(studies),
        active_trials_total=len(active),
        by_phase=dict(by_phase),
        by_status=dict(by_status),
        top_conditions=tuple(
            {"condition": name, "count": count} for name, count in conditions.most_common(top_conditions)
        ),
        upcoming_readouts=tuple(
            {
                "nct_id": s.nct_id,
                "title": s.title,
                "phase": phase_of(s),
                "condition": s.conditions[0] if s.conditions else None,
                "primary_completion_date": s.primary_completion.isoformat()
                if s.primary_completion
                else None,
                "enrollment": s.enrollment,
                "url": s.url,
            }
            for s in readouts
        ),
        started_ttm=started_ttm,
        started_prior_ttm=started_prior,
        discontinued_all_time=sum(1 for s in studies if (s.status or "") in DISCONTINUED_STATUSES),
        completed_all_time=sum(1 for s in studies if (s.status or "") in COMPLETED_STATUSES),
        active_late_stage=sum(1 for s in active if phase_of(s) in LATE_STAGE),
    )


# --------------------------------------------------------------------------- #
# Metrics (SPEC §6)
# --------------------------------------------------------------------------- #


def pipeline_depth_score(pipeline: Pipeline) -> MetricResult:
    """`1×Ph1 + 3×Ph2 + 8×Ph3 + 12×Ph4`, active trials only."""
    weighted = (
        DEPTH_WEIGHTS["PHASE1"] * pipeline.by_phase.get("phase_1", 0)
        + DEPTH_WEIGHTS["PHASE2"] * pipeline.by_phase.get("phase_2", 0)
        + DEPTH_WEIGHTS["PHASE3"] * pipeline.by_phase.get("phase_3", 0)
        + DEPTH_WEIGHTS["PHASE4"] * pipeline.by_phase.get("phase_4", 0)
    )
    if not pipeline.active_trials_total:
        return MetricResult(
            name="pipeline_depth_score", value=None, suppressed_by=("no_active_trials",)
        )
    return MetricResult(name="pipeline_depth_score", value=float(weighted))


def pipeline_concentration(studies: Sequence[Study]) -> MetricResult:
    """Herfindahl index across the therapeutic areas of active trials.

    1.0 means every active trial addresses one condition — single-asset or
    single-area risk. A trial listing several conditions contributes a fraction
    of itself to each, so a broad trial does not count as several narrow ones.
    """
    active = [s for s in studies if is_active(s)]
    weights: Counter[str] = Counter()
    for study in active:
        if not study.conditions:
            continue
        share = 1.0 / len(study.conditions)
        for condition in study.conditions:
            weights[condition] += share

    total = sum(weights.values())
    if not total:
        return MetricResult(
            name="pipeline_concentration", value=None, suppressed_by=("no_active_trials",)
        )
    hhi = sum((w / total) ** 2 for w in weights.values())
    return MetricResult(name="pipeline_concentration", value=hhi)


def clinical_momentum(pipeline: Pipeline) -> MetricResult:
    """Trials started in the trailing twelve months, less the prior twelve.

    Positive means the pipeline is expanding. Registration lags the start date,
    so the most recent months are systematically under-counted and a small
    negative reading is not evidence of contraction.
    """
    return MetricResult(
        name="clinical_momentum",
        value=float(pipeline.started_ttm - pipeline.started_prior_ttm),
    )


def discontinuation_rate(pipeline: Pipeline) -> MetricResult:
    """`(terminated + withdrawn) / (completed + terminated + withdrawn)`, all time.

    Suppressed below `DISCONTINUATION_MIN_TRIALS` resolved trials: on a handful,
    one termination swings the rate by tens of percentage points and the figure
    describes the sample rather than the company.
    """
    resolved = pipeline.completed_all_time + pipeline.discontinued_all_time
    if resolved < DISCONTINUATION_MIN_TRIALS:
        return MetricResult(
            name="discontinuation_rate",
            value=None,
            suppressed_by=("too_few_resolved_trials",),
        )
    return MetricResult(
        name="discontinuation_rate", value=pipeline.discontinued_all_time / resolved
    )


#: How far the two sources' as-of dates may drift before the gap is worth naming
#: on a metric that spans them. A quarter: SEC facts arrive quarterly, so a gap
#: inside one reporting period is expected rather than notable.
SOURCE_GAP_TOLERANCE_DAYS = 100

FLAG_SOURCE_DATE_GAP = "cross_source_date_gap"


def rnd_per_late_stage_programme(
    rnd: QuarterlySeries, pipeline: Pipeline
) -> MetricResult:
    """`R&D TTM / count(active Phase 2 and 3 trials)` (SPEC §6).

    The one metric that spans both sources, and the only place the period
    alignment invariant cannot be satisfied: a trailing-twelve-month R&D figure
    ends on a fiscal quarter end, while the trial count is whatever the registry
    said at fetch time. The two were never true at the same instant, so the gap
    between them travels with the value rather than being quietly ignored.

    Crude by construction, and comparable only within a subsector.
    """
    spend: PeriodValue | None = rnd.trailing_twelve_months()
    if spend is None:
        return MetricResult(
            name="rnd_per_late_stage_programme", value=None, suppressed_by=("no_rnd_figure",)
        )
    if not pipeline.active_late_stage:
        return MetricResult(
            name="rnd_per_late_stage_programme",
            value=None,
            inputs=(spend,),
            suppressed_by=("no_active_late_stage_trials",),
        )

    gap = abs((pipeline.as_of - spend.end).days)
    extra = (FLAG_SOURCE_DATE_GAP,) if gap > SOURCE_GAP_TOLERANCE_DAYS else ()

    return guard_metric(
        "rnd_per_late_stage_programme",
        lambda: spend.val / pipeline.active_late_stage,
        (spend,),
        extra_flags=extra,
    )


def all_pipeline_metrics(
    studies: Sequence[Study], pipeline: Pipeline, rnd: QuarterlySeries | None
) -> dict[str, MetricResult]:
    metrics = {
        "pipeline_depth_score": pipeline_depth_score(pipeline),
        "pipeline_concentration": pipeline_concentration(studies),
        "clinical_momentum": clinical_momentum(pipeline),
        "discontinuation_rate": discontinuation_rate(pipeline),
    }
    if rnd is not None:
        metrics["rnd_per_late_stage_programme"] = rnd_per_late_stage_programme(rnd, pipeline)
    return metrics
