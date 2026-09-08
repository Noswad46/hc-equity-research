"""Derived metrics (SPEC §6).

Every metric here routes through `guard_metric`, so a flag raised at the fact
layer can suppress a metric rather than merely annotate it. The formulas are
published on the methodology page; the point of this module is that the
arithmetic and its refusals live in one auditable place.

Two refusals are worth stating up front.

**Growth on a trivial base is not reported.** Vir's revenue moved from a $19m
trailing year to $303m, which is arithmetically +1496% and tells a reader
nothing except that the prior year was near zero. Below `GROWTH_FLOOR` the
metric is `n/m` — not a number, not zero, and not infinity — and the screener
sorts it to the end of the column in both directions so these names cannot top a
growth screen.

**Runway is not computed from cash that includes restricted balances.** Where the
cash figure came from the cash-flow statement's reconciling total, restricted
cash is netted off if the filer tags it separately. Where it does not — Gilead —
the flag propagates and the metric is suppressed, because restricted cash cannot
fund operations and a runway inflated by it would be wrong in the direction that
matters most for the names runway exists to describe.
"""

from __future__ import annotations

import datetime as dt
from typing import Mapping

from transform.fundamentals import (
    BASIS_CASH_INCLUDING_RESTRICTED,
    BLOCKING_FLAGS,
    FLAG_CASH_INCLUDES_RESTRICTED,
    MetricResult,
    PeriodValue,
    QuarterlySeries,
    guard_metric,
)

#: Prior-year revenue below this makes a growth percentage noise rather than
#: signal. Published on the methodology page.
GROWTH_FLOOR = 50_000_000.0

#: Reason codes this module can attach.
NOT_MEANINGFUL = "not_meaningful_small_base"
RESTRICTED_CASH_NOT_SEPARABLE = "restricted_cash_not_separable"
NO_BURN = "operating_cash_flow_positive"


def _ttm(series: QuarterlySeries | None, as_of: dt.date | None = None) -> PeriodValue | None:
    return series.trailing_twelve_months(as_of) if series else None


def _aligned_ttm(series: QuarterlySeries | None, as_of: dt.date | None) -> PeriodValue | None:
    """A trailing year ending exactly at `as_of`, or nothing."""
    if series is None or as_of is None:
        return None
    value = series.trailing_twelve_months(as_of)
    return value if value is not None and value.end == as_of else None


PERIOD_MISMATCH = "period_mismatch"


def ratio(
    name: str,
    numerator: QuarterlySeries | None,
    denominator: QuarterlySeries | None,
    *,
    as_of: dt.date | None,
    extra_flags: tuple[str, ...] = (),
    allow_negative_denominator: bool = False,
) -> MetricResult:
    """Every two-sided metric in this module is built here, and only here.

    The alignment rule is a property of this constructor rather than a check
    inside each metric, because a check repeated per metric is a check that the
    next metric forgets. Both sides must produce a trailing year ending on
    exactly the same date or the result is null: J&J stopped tagging
    `OperatingIncomeLoss` in 2015, and pairing that with 2026 revenue produced a
    22% operating margin describing neither year.

    Cross-source ratios use `cross_source_ratio`, which adds the source-date gap
    on top of this.
    """
    top = _aligned_ttm(numerator, as_of)
    bottom = _aligned_ttm(denominator, as_of)
    inputs = tuple(v for v in (top, bottom) if v is not None)

    if denominator is None or not denominator.values:
        # No denominator series at all is a different failure from two series
        # that exist but cannot be lined up.
        return MetricResult(
            name=name, value=None, inputs=inputs, suppressed_by=("no_denominator",)
        )
    if top is None or bottom is None:
        return MetricResult(
            name=name, value=None, inputs=inputs, suppressed_by=(PERIOD_MISMATCH,)
        )
    if not bottom.val or (bottom.val < 0 and not allow_negative_denominator):
        return MetricResult(
            name=name, value=None, inputs=inputs, suppressed_by=("no_denominator",)
        )
    return guard_metric(name, lambda: top.val / bottom.val, inputs, extra_flags=extra_flags)


def _anchor_end(revenue: QuarterlySeries) -> dt.date | None:
    return revenue.values[-1].end if revenue.values else None


def _latest(series: QuarterlySeries | None) -> PeriodValue | None:
    return series.values[-1] if series and series.values else None


def revenue_growth(revenue: QuarterlySeries, as_of: dt.date | None = None) -> MetricResult:
    """TTM revenue against the prior TTM, suppressed on a trivial base.

    `n/m` is signalled by a null value carrying `not_meaningful_small_base`. It is
    deliberately not zero and not infinity: either would sort into the middle or
    the top of a growth screen, which is exactly the failure this guards against.
    """
    base = revenue.growth(as_of)
    if base.value is None:
        return base

    end = as_of or (revenue.values[-1].end if revenue.values else None)
    current = _ttm(revenue, end)
    prior = _ttm(revenue, current.start - dt.timedelta(days=1)) if current else None
    if prior is not None and abs(prior.val) < GROWTH_FLOOR:
        return MetricResult(
            name=base.name,
            value=None,
            inputs=base.inputs,
            flags=base.flags,
            suppressed_by=(NOT_MEANINGFUL,),
        )
    return base


def operating_margin(
    operating_income: QuarterlySeries, revenue: QuarterlySeries
) -> MetricResult:
    """Operating income TTM over revenue TTM.

    Carries whatever flags the operating income series carried, so a margin built
    on a reconstructed subtotal is marked as such wherever it is shown.
    """
    return ratio("operating_margin", operating_income, revenue, as_of=_anchor_end(revenue))


def ocf_margin(ocf: QuarterlySeries, revenue: QuarterlySeries) -> MetricResult:
    return ratio("ocf_margin", ocf, revenue, as_of=_anchor_end(revenue))


def net_margin(net_income: QuarterlySeries, revenue: QuarterlySeries) -> MetricResult:
    """Net income TTM over revenue TTM.

    `NetIncomeLoss` is universally tagged, which is why this carries the headline
    alongside OCF margin while operating margin sits behind them.
    """
    return ratio("net_margin", net_income, revenue, as_of=_anchor_end(revenue))


def rnd_intensity(
    rnd: QuarterlySeries, revenue: QuarterlySeries, opex: QuarterlySeries | None = None
) -> MetricResult:
    """R&D TTM over revenue TTM, or over operating expenses for pre-revenue names.

    SPEC §6 specifies the opex variant and requires it to be flagged, because the
    two denominators are not comparable — one measures how much of what the
    company earns goes into research, the other how much of what it spends does.
    """
    end = _anchor_end(revenue)
    sales = _aligned_ttm(revenue, end)

    if sales is not None and sales.val > 0:
        return ratio("rnd_intensity", rnd, revenue, as_of=end)

    return ratio(
        "rnd_intensity", rnd, opex, as_of=end, extra_flags=("rnd_intensity_over_opex",)
    )


def liquid_assets(
    cash: QuarterlySeries,
    short_term_investments: QuarterlySeries | None,
    restricted_cash: QuarterlySeries | None,
) -> tuple[PeriodValue | None, float | None, tuple[str, ...]]:
    """Cash plus short-term investments, with restricted balances removed.

    Returns `(anchor, value, flags)`. The anchor is the cash reading the figure is
    dated from; `flags` carries `cash_includes_restricted` onward when the cash
    tag was the broader cash-flow one and the restricted portion could not be
    separated out.
    """
    latest = _latest(cash)
    if latest is None:
        return None, None, ()

    total = latest.val
    flags: list[str] = []

    if latest.measurement_basis == BASIS_CASH_INCLUDING_RESTRICTED:
        restricted = restricted_cash.by_end().get(latest.end) if restricted_cash else None
        if restricted is not None:
            total -= restricted.val  # separable: net it off and carry on
        else:
            flags.append(FLAG_CASH_INCLUDES_RESTRICTED)

    investments = short_term_investments.by_end().get(latest.end) if short_term_investments else None
    if investments is not None:
        total += investments.val

    return latest, total, tuple(flags)


def net_cash(
    cash: QuarterlySeries,
    short_term_investments: QuarterlySeries | None,
    debt: QuarterlySeries | None,
    restricted_cash: QuarterlySeries | None = None,
) -> MetricResult:
    """`cash + short-term investments − total debt` (SPEC §6).

    A slight overstatement from restricted cash is tolerable here — this is a
    balance-sheet position, not a divisor — so the flag travels with the figure
    rather than suppressing it.
    """
    anchor, liquid, flags = liquid_assets(cash, short_term_investments, restricted_cash)
    if anchor is None or liquid is None:
        return MetricResult(name="net_cash", value=None, suppressed_by=("no_cash_figure",))

    borrowings = debt.by_end().get(anchor.end) if debt else None
    inputs = tuple(v for v in (anchor, borrowings) if v is not None)
    owed = borrowings.val if borrowings else 0.0
    # No debt tag is not the same claim as no debt. Vir and Vertex genuinely
    # carry no borrowings; a filer that simply failed to tag them looks identical
    # from here, so the difference is surfaced rather than assumed away.
    extra = flags + (() if borrowings else ("debt_not_tagged",))

    return guard_metric("net_cash", lambda: liquid - owed, inputs, extra_flags=extra)


def cash_runway_quarters(
    cash: QuarterlySeries,
    ocf: QuarterlySeries,
    short_term_investments: QuarterlySeries | None = None,
    restricted_cash: QuarterlySeries | None = None,
) -> MetricResult:
    """`(cash + ST investments) / mean(abs(quarterly OCF))` over the trailing four.

    Null when trailing operating cash flow is positive — a company funding itself
    from operations has no runway to run out of, and reporting a large number
    there would invite exactly the wrong reading.

    Suppressed when the cash figure includes restricted balances that could not be
    separated. Runway is the metric this project exists to get right for
    clinical-stage names, and inflating the numerator with money the company is
    contractually barred from spending is a conceptual error, not a rounding one.
    """
    anchor, liquid, flags = liquid_assets(cash, short_term_investments, restricted_cash)
    if anchor is None or liquid is None:
        return MetricResult(name="cash_runway_quarters", value=None, suppressed_by=("no_cash_figure",))

    window = ocf.window(anchor.end, 4) if ocf.values else None
    if window is None:
        window = ocf.window(ocf.values[-1].end, 4) if ocf.values else None
    if window is None:
        return MetricResult(
            name="cash_runway_quarters", value=None, suppressed_by=("incomplete_window",)
        )

    total_flow = sum(v.val for v in window)
    if total_flow >= 0:
        return MetricResult(
            name="cash_runway_quarters",
            value=None,
            inputs=(anchor,) + window,
            suppressed_by=(NO_BURN,),
        )

    burn = sum(abs(v.val) for v in window) / len(window)
    if not burn:
        return MetricResult(
            name="cash_runway_quarters", value=None, suppressed_by=("incomplete_window",)
        )

    if FLAG_CASH_INCLUDES_RESTRICTED in flags:
        return MetricResult(
            name="cash_runway_quarters",
            value=None,
            inputs=(anchor,) + window,
            flags=flags,
            suppressed_by=(RESTRICTED_CASH_NOT_SEPARABLE,),
        )

    return guard_metric(
        "cash_runway_quarters",
        lambda: liquid / burn,
        (anchor,) + window,
        blocking=BLOCKING_FLAGS,
    )


def all_metrics(series: Mapping[str, QuarterlySeries]) -> dict[str, MetricResult]:
    """Every SPEC §6 metric computable from fundamentals alone."""
    revenue = series["revenue"]
    return {
        "revenue_growth_yoy": revenue_growth(revenue),
        "operating_margin": operating_margin(series["operating_income"], revenue),
        "ocf_margin": ocf_margin(series["ocf"], revenue),
        "net_margin": net_margin(series["net_income"], revenue),
        "rnd_intensity": rnd_intensity(series["rnd"], revenue, series.get("opex")),
        "net_cash": net_cash(
            series["cash"],
            series.get("short_term_investments"),
            series.get("debt"),
            series.get("restricted_cash"),
        ),
        "cash_runway_quarters": cash_runway_quarters(
            series["cash"],
            series["ocf"],
            series.get("short_term_investments"),
            series.get("restricted_cash"),
        ),
    }
