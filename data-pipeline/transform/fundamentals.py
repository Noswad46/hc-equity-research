"""XBRL tag resolution and year-to-date → discrete-quarter conversion.

This is the transform half of SPEC §5.1, and the warning in SPEC §11 applies:
every metric downstream inherits errors made here, and those errors are hard to
spot once they are rendered as confident-looking numbers in a table. Three
behaviours exist specifically to keep that from happening.

**Tag resolution is per period, not per company.** Filers migrate tags mid-life —
Pfizer's `RevenueFromContractWithCustomerExcludingAssessedTax` stops in 2023 and
`Revenues` takes over — so resolving one tag for the whole company either loses
recent data or loses history. Instead the chain is walked once per period and the
tag that supplied each value is recorded on that value, which is what makes the
footnote rule in SPEC §6 possible.

**Arithmetic never crosses tags.** Discrete quarters are derived inside a single
tag's fact set and only then merged by chain preference. Differencing an annual
figure tagged `Revenues` against a nine-month figure tagged
`RevenueFromContractWithCustomerExcludingAssessedTax` would subtract two
different definitions of revenue and produce a plausible, wrong number.

**Restatements resolve to the most recently filed value.** A period is often
reported several times across filings; the latest wins, on both sides of every
subtraction, so a derived quarter is never a mix of vintages.

Two things that discipline still cannot fix are detected and flagged instead of
being quietly emitted:

* A period whose annual figure was restated while its quarters were not. Merck's
  FY2020 was restated for the Organon spin-off, so its 2020 quarters no longer
  sum to its annual. `reconcile_fiscal_years` catches this.
* A filer whose chain tags are not interchangeable. Pfizer tags total revenue as
  `RevenueFromContractWithCustomerExcludingAssessedTax` in its 10-Qs, but in the
  10-K uses that tag for the narrower revenue-from-contracts subtotal and
  `Revenues` for the total. The two agree on every quarterly and year-to-date
  period and disagree only on annuals, so a Q4 derived as annual-minus-nine-months
  silently absorbs the difference — $15.8bn against the $25.1bn the same filing
  supports under the other tag. `detect_tag_divergence` finds the disagreeing
  periods and marks every quarter derived from one.

Neither is corrected automatically. Picking a winner would mean encoding a guess
about which tag the filer meant, and SPEC §4's warning about silent,
plausible-looking errors applies to tag choice as much as to name matching.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "ANNUAL_DAYS",
    "CONCEPT_CHAINS",
    "M1_CONCEPTS",
    "PERIODIC_FORMS",
    "QUARTER_DAYS",
    "Basis",
    "Concept",
    "ConceptKind",
    "ConceptResolution",
    "Fact",
    "FundamentalsError",
    "PeriodValue",
    "QuarterRow",
    "QuarterlySeries",
    "QuarterlyTable",
    "Reconciliation",
    "TagDivergence",
    "UnsupportedConcept",
    "annual_totals",
    "build_quarterly_table",
    "detect_tag_divergence",
    "discrete_quarters",
    "extract_facts",
    "interchangeable_tag_pairs",
    "latest_by_period",
    "quarterly_series",
    "reconcile_fiscal_years",
    "resolve_concept",
]


class FundamentalsError(Exception):
    """Base class for failures raised by this module."""


class UnsupportedConcept(FundamentalsError):
    """The concept exists in SPEC §5.1 but M1 does not implement its kind."""


DEFAULT_TAXONOMY = "us-gaap"
DEFAULT_UNIT = "USD"

#: SPEC §5.1: filter facts by form. Amendments are kept — they are restatements,
#: and `latest_by_period` already prefers whichever was filed most recently.
#: Everything else (8-K, S-1, 424B, 20-F) is dropped: those carry figures on
#: bases that do not belong in a 10-K/10-Q period series.
PERIODIC_FORMS = ("10-K", "10-Q")

#: Inclusive day-count windows for classifying a fact's period, wide enough for
#: 52/53-week fiscal calendars (Pfizer's quarters run 91–98 days and its quarter
#: ends drift by several days year to year).
QUARTER_DAYS = (80, 100)
ANNUAL_DAYS = (340, 380)


class ConceptKind(str, Enum):
    """How a concept's facts behave over time."""

    #: Measured across a period — an income-statement or cash-flow line. These are
    #: the ones that need year-to-date unwinding.
    DURATION = "duration"
    #: Measured at an instant — a balance-sheet line.
    INSTANT = "instant"
    #: The sum of several tags rather than a fallback chain.
    SUM = "sum"


class Basis(str, Enum):
    """Where a discrete quarterly value came from."""

    #: The filer tagged this exact quarter as its own fact.
    REPORTED = "reported"
    #: Computed by differencing two year-to-date facts.
    DERIVED = "derived"


@dataclass(frozen=True)
class Concept:
    """A named concept and its ordered tag fallback chain (SPEC §5.1)."""

    name: str
    kind: ConceptKind
    tags: tuple[str, ...]
    label: str

    @property
    def primary_tag(self) -> str:
        return self.tags[0]


def _concept(name: str, kind: ConceptKind, label: str, *tags: str) -> tuple[str, Concept]:
    return name, Concept(name=name, kind=kind, tags=tags, label=label)


#: The fallback chains exactly as SPEC §5.1 defines them.
#:
#: Known gap, left in place rather than silently widened: the R&D chain has a
#: single entry, and neither Pfizer nor Johnson & Johnson tags quarterly R&D that
#: way — both use `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost`.
#: R&D therefore resolves to nothing for those two filers, and the resolution
#: reports the near-miss tags it saw so the gap is visible rather than silent.
CONCEPT_CHAINS: Mapping[str, Concept] = dict(
    [
        _concept(
            "revenue",
            ConceptKind.DURATION,
            "Revenue",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
        ),
        _concept("rnd", ConceptKind.DURATION, "R&D expense", "ResearchAndDevelopmentExpense"),
        _concept(
            "ocf",
            ConceptKind.DURATION,
            "Operating cash flow",
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
        _concept("operating_income", ConceptKind.DURATION, "Operating income", "OperatingIncomeLoss"),
        _concept("net_income", ConceptKind.DURATION, "Net income", "NetIncomeLoss"),
        _concept("cash", ConceptKind.INSTANT, "Cash", "CashAndCashEquivalentsAtCarryingValue"),
        _concept(
            "short_term_investments",
            ConceptKind.INSTANT,
            "Short-term investments",
            "ShortTermInvestments",
            "MarketableSecuritiesCurrent",
            "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
        ),
        _concept(
            "shares_outstanding",
            ConceptKind.INSTANT,
            "Shares outstanding",
            "CommonStockSharesOutstanding",
        ),
        _concept("debt", ConceptKind.SUM, "Total debt", "LongTermDebtNoncurrent", "LongTermDebtCurrent"),
    ]
)

#: The three concepts M1 delivers.
M1_CONCEPTS: tuple[str, ...] = ("revenue", "rnd", "ocf")

#: Tags close enough to a chain entry to be worth naming when the chain resolves
#: to nothing — the difference between "this filer reports no R&D" and "this
#: filer reports R&D under a tag the chain does not list".
_NEAR_MISS_HINTS: Mapping[str, tuple[str, ...]] = {
    "revenue": ("Revenue",),
    "rnd": ("ResearchAndDevelopment",),
    "ocf": ("OperatingActivities",),
    "operating_income": ("OperatingIncome",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "cash": ("CashAndCashEquivalents",),
    "short_term_investments": ("MarketableSecurities", "ShortTermInvestments"),
    "shares_outstanding": ("SharesOutstanding",),
    "debt": ("LongTermDebt",),
}

# Flag vocabulary. Company-level flags stand alone; concept-level flags are
# prefixed with the concept name, e.g. "revenue:fallback_tag".
FLAG_NO_TAXONOMY = "no_us_gaap_facts"
FLAG_NO_CONCEPTS_RESOLVED = "no_concepts_resolved"
FLAG_NO_TAG_RESOLVED = "no_tag_resolved"
FLAG_NO_QUARTERS = "no_quarters_derived"
FLAG_FALLBACK_TAG = "fallback_tag"
FLAG_MIXED_TAGS = "mixed_tags"
FLAG_FY_RECONCILIATION_FAILED = "fy_reconciliation_failed"
FLAG_CHAIN_TAGS_DIVERGE = "chain_tags_diverge"
FLAG_TAG_BASIS_UNCERTAIN = "tag_basis_uncertain"
FLAG_PERIOD_START_MISMATCH = "period_start_mismatch"


# --------------------------------------------------------------------------- #
# Facts
# --------------------------------------------------------------------------- #


def _parse_date(value: object) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class Fact:
    """One XBRL fact from `companyfacts`, normalised."""

    tag: str
    taxonomy: str
    unit: str
    end: dt.date
    val: float
    form: str
    accn: str
    filed: dt.date
    start: dt.date | None = None
    fy: int | None = None
    fp: str | None = None

    @property
    def days(self) -> int | None:
        """Inclusive length of the period, or None for an instant fact."""
        if self.start is None:
            return None
        return (self.end - self.start).days + 1

    @property
    def base_form(self) -> str:
        """`10-K/A` -> `10-K`."""
        return self.form.split("/", 1)[0]

    @property
    def is_amendment(self) -> bool:
        return "/A" in self.form

    @property
    def vintage(self) -> tuple[dt.date, str]:
        """Sort key identifying how recently this value was asserted."""
        return (self.filed, self.accn)

    def _in(self, window: tuple[int, int]) -> bool:
        days = self.days
        return days is not None and window[0] <= days <= window[1]

    @property
    def is_quarterly(self) -> bool:
        return self._in(QUARTER_DAYS)

    @property
    def is_annual(self) -> bool:
        return self._in(ANNUAL_DAYS)


def extract_facts(
    companyfacts: Mapping[str, Any],
    tag: str,
    *,
    taxonomy: str = DEFAULT_TAXONOMY,
    unit: str = DEFAULT_UNIT,
    forms: Sequence[str] = PERIODIC_FORMS,
    duration_only: bool = True,
) -> list[Fact]:
    """Pull one tag's facts out of a `companyfacts` payload.

    Filters to the named taxonomy and unit and to periodic forms. Taxonomy is
    matched explicitly rather than by tag name, because IFRS filers publish an
    `ifrs-full:ResearchAndDevelopmentExpense` whose local name collides with the
    us-gaap tag while its figures are not on a comparable basis.
    """
    node = companyfacts.get("facts", {})
    if not isinstance(node, Mapping):
        return []
    tags = node.get(taxonomy)
    if not isinstance(tags, Mapping):
        return []
    entry = tags.get(tag)
    if not isinstance(entry, Mapping):
        return []
    rows = entry.get("units", {})
    if not isinstance(rows, Mapping):
        return []

    allowed = frozenset(forms)
    out: list[Fact] = []
    for raw in rows.get(unit, []):
        if not isinstance(raw, Mapping):
            continue
        form = raw.get("form")
        if not isinstance(form, str) or form.split("/", 1)[0] not in allowed:
            continue

        end = _parse_date(raw.get("end"))
        filed = _parse_date(raw.get("filed"))
        start = _parse_date(raw.get("start"))
        val = raw.get("val")
        accn = raw.get("accn")
        if end is None or filed is None or not isinstance(accn, str):
            continue
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            continue
        if duration_only and start is None:
            continue
        if start is not None and start > end:
            continue

        out.append(
            Fact(
                tag=tag,
                taxonomy=taxonomy,
                unit=unit,
                start=start,
                end=end,
                val=float(val),
                form=form,
                accn=accn,
                filed=filed,
                fy=raw.get("fy") if isinstance(raw.get("fy"), int) else None,
                fp=raw.get("fp") if isinstance(raw.get("fp"), str) else None,
            )
        )
    return out


def latest_by_period(facts: Iterable[Fact]) -> dict[tuple[dt.date | None, dt.date], Fact]:
    """Collapse restatements: one fact per period, most recently filed wins.

    SPEC §5.1 requires preferring the most recently filed value where a period
    has been restated. Doing it here, before any arithmetic, is what keeps both
    sides of a year-to-date subtraction on the same vintage.
    """
    best: dict[tuple[dt.date | None, dt.date], Fact] = {}
    for fact in facts:
        key = (fact.start, fact.end)
        current = best.get(key)
        if current is None or fact.vintage > current.vintage:
            best[key] = fact
    return best


# --------------------------------------------------------------------------- #
# Period values
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PeriodValue:
    """A figure for one period, with the provenance needed to audit it."""

    concept: str
    tag: str
    start: dt.date
    end: dt.date
    val: float
    basis: Basis
    filed: dt.date
    accns: tuple[str, ...]
    forms: tuple[str, ...]
    taxonomy: str = DEFAULT_TAXONOMY
    unit: str = DEFAULT_UNIT
    #: The source periods this value was computed from. Empty for a reported
    #: value; the (longer, shorter) pair of year-to-date periods for a derived
    #: one. Used to tell whether a derived value leaned on a period whose tagging
    #: is in doubt.
    derived_from: tuple[tuple[dt.date, dt.date], ...] = ()
    #: Every tag behind this figure. One entry for a single quarter; possibly
    #: several for an aggregate such as a trailing twelve months.
    contributing_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.contributing_tags:
            object.__setattr__(self, "contributing_tags", (self.tag,))

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "period_start": self.start.isoformat(),
            "period_end": self.end.isoformat(),
            "value": self.val,
            "unit": self.unit,
            "tag": self.tag,
            "taxonomy": self.taxonomy,
            "basis": self.basis.value,
            "filed": self.filed.isoformat(),
            "accns": list(self.accns),
            "forms": list(self.forms),
            "derived_from": [[s.isoformat(), e.isoformat()] for s, e in self.derived_from],
            "contributing_tags": list(self.contributing_tags),
        }


def _preference(value: PeriodValue) -> tuple[int, dt.date, str]:
    """Higher sorts better: a reported quarter beats a derived one, then recency."""
    return (0 if value.basis is Basis.REPORTED else -1, value.filed, value.accns[0])


def discrete_quarters(facts: Iterable[Fact], *, concept: str = "") -> dict[dt.date, PeriodValue]:
    """Discrete quarters for a *single* tag, keyed by period end.

    Two sources, in preference order:

    1. Facts whose own period is already about a quarter long. A calendar-year
       filer's Q1 is both its first quarter and its first year-to-date figure, so
       it lands here.
    2. Differences between consecutive year-to-date facts sharing a start date —
       nine months minus six months gives Q3, and the annual minus nine months
       gives the Q4 that is almost never filed on its own.

    Start dates are matched exactly. Filers on a 52/53-week calendar occasionally
    shift a start by a few days between filings; tolerating that would risk
    differencing two unrelated periods, and a missing quarter is a much better
    failure than a confidently wrong one.
    """
    observed = latest_by_period(facts)
    out: dict[dt.date, PeriodValue] = {}

    def offer(candidate: PeriodValue) -> None:
        current = out.get(candidate.end)
        if current is None or _preference(candidate) > _preference(current):
            out[candidate.end] = candidate

    for (start, end), fact in observed.items():
        if start is not None and fact.is_quarterly:
            offer(
                PeriodValue(
                    concept=concept,
                    tag=fact.tag,
                    start=start,
                    end=end,
                    val=fact.val,
                    basis=Basis.REPORTED,
                    filed=fact.filed,
                    accns=(fact.accn,),
                    forms=(fact.form,),
                    taxonomy=fact.taxonomy,
                    unit=fact.unit,
                )
            )

    by_start: dict[dt.date, list[dt.date]] = {}
    for start, end in observed:
        if start is not None:
            by_start.setdefault(start, []).append(end)

    for start, ends in by_start.items():
        ends.sort()
        for earlier, later in zip(ends, ends[1:]):
            residual = (later - earlier).days
            if not QUARTER_DAYS[0] <= residual <= QUARTER_DAYS[1]:
                continue
            longer = observed[(start, later)]
            shorter = observed[(start, earlier)]
            offer(
                PeriodValue(
                    concept=concept,
                    tag=longer.tag,
                    start=earlier + dt.timedelta(days=1),
                    end=later,
                    val=longer.val - shorter.val,
                    basis=Basis.DERIVED,
                    filed=max(longer.filed, shorter.filed),
                    accns=(longer.accn, shorter.accn),
                    forms=(longer.form, shorter.form),
                    taxonomy=longer.taxonomy,
                    unit=longer.unit,
                    derived_from=((start, later), (start, earlier)),
                )
            )

    return out


def annual_totals(facts: Iterable[Fact], *, concept: str = "") -> dict[dt.date, PeriodValue]:
    """Full-year figures for a single tag, keyed by fiscal year end.

    Restricted to 10-K forms: a 10-K is the only filing that reports a complete
    fiscal year, so this cannot pick up a trailing-twelve-month figure by mistake.
    """
    out: dict[dt.date, PeriodValue] = {}
    for (start, end), fact in latest_by_period(facts).items():
        if start is None or not fact.is_annual or fact.base_form != "10-K":
            continue
        out[end] = PeriodValue(
            concept=concept,
            tag=fact.tag,
            start=start,
            end=end,
            val=fact.val,
            basis=Basis.REPORTED,
            filed=fact.filed,
            accns=(fact.accn,),
            forms=(fact.form,),
            taxonomy=fact.taxonomy,
            unit=fact.unit,
        )
    return out


# --------------------------------------------------------------------------- #
# Chain resolution
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ConceptResolution:
    """Which tags in a concept's chain were available, and which were used."""

    concept: str
    chain: tuple[str, ...]
    tags_available: tuple[str, ...]
    tags_used: tuple[str, ...]
    near_miss_tags: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return bool(self.tags_used)

    @property
    def primary_tag(self) -> str:
        return self.chain[0]

    @property
    def uses_fallback(self) -> bool:
        """True when any value came from a tag other than the chain's first entry."""
        return any(tag != self.primary_tag for tag in self.tags_used)

    @property
    def mixed(self) -> bool:
        """True when the series is not on a single tag's basis end to end."""
        return len(self.tags_used) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "chain": list(self.chain),
            "tags_available": list(self.tags_available),
            "tags_used": list(self.tags_used),
            "primary_tag": self.primary_tag,
            "uses_fallback": self.uses_fallback,
            "mixed_tags": self.mixed,
            "near_miss_tags": list(self.near_miss_tags),
        }


def _lookup_concept(concept: str | Concept) -> Concept:
    if isinstance(concept, Concept):
        return concept
    try:
        return CONCEPT_CHAINS[concept]
    except KeyError:
        raise FundamentalsError(
            f"unknown concept {concept!r}; expected one of {', '.join(sorted(CONCEPT_CHAINS))}"
        ) from None


def _near_misses(
    companyfacts: Mapping[str, Any], concept: Concept, *, taxonomy: str
) -> tuple[str, ...]:
    """Tags in the filing that look like they belong to this concept but are not in the chain."""
    node = companyfacts.get("facts", {})
    tags = node.get(taxonomy) if isinstance(node, Mapping) else None
    if not isinstance(tags, Mapping):
        return ()
    hints = _NEAR_MISS_HINTS.get(concept.name, ())
    if not hints:
        return ()
    chain = set(concept.tags)
    return tuple(
        sorted(t for t in tags if t not in chain and any(h in t for h in hints))
    )


def resolve_concept(
    companyfacts: Mapping[str, Any],
    concept: str | Concept,
    *,
    taxonomy: str = DEFAULT_TAXONOMY,
    unit: str = DEFAULT_UNIT,
) -> ConceptResolution:
    """Report which chain tags carry usable facts, without computing anything.

    `tags_used` is filled in by `quarterly_series`, which knows which tags
    actually supplied a value; a tag can carry facts and still contribute nothing
    if an earlier chain entry covers every period it touches.
    """
    concept = _lookup_concept(concept)
    available = tuple(
        tag
        for tag in concept.tags
        if extract_facts(
            companyfacts,
            tag,
            taxonomy=taxonomy,
            unit=unit,
            duration_only=concept.kind is ConceptKind.DURATION,
        )
    )
    return ConceptResolution(
        concept=concept.name,
        chain=concept.tags,
        tags_available=available,
        tags_used=(),
        near_miss_tags=() if available else _near_misses(companyfacts, concept, taxonomy=taxonomy),
    )


# --------------------------------------------------------------------------- #
# Series
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TagDivergence:
    """One period reported under two chain tags with materially different values."""

    start: dt.date
    end: dt.date
    values: Mapping[str, float]

    @property
    def spread(self) -> float:
        return max(self.values.values()) - min(self.values.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_start": self.start.isoformat(),
            "period_end": self.end.isoformat(),
            "values": dict(self.values),
            "spread": self.spread,
        }


def detect_tag_divergence(
    facts_by_tag: Mapping[str, Mapping[tuple[dt.date | None, dt.date], Fact]],
    *,
    rel_tol: float = 0.005,
    abs_tol: float = 2_000_000.0,
) -> list[TagDivergence]:
    """Find periods where two tags in the same chain disagree.

    A fallback chain assumes its entries are alternative spellings of one
    concept. When a filer reports the same period under two of them with
    different values, that assumption is false for that filer, and any figure
    derived by combining periods across those tags' shared history is suspect.

    Pfizer is the case this exists for: `RevenueFromContractWithCustomerExcludingAssessedTax`
    and `Revenues` match on every quarter and year-to-date period and diverge
    only on fiscal years, which is precisely what corrupts a Q4 derived as
    annual-minus-nine-months.
    """
    periods: dict[tuple[dt.date | None, dt.date], dict[str, float]] = {}
    for tag, observed in facts_by_tag.items():
        for key, fact in observed.items():
            periods.setdefault(key, {})[tag] = fact.val

    out: list[TagDivergence] = []
    for (start, end), values in sorted(periods.items(), key=lambda kv: (kv[0][1], kv[0][0] or dt.date.min)):
        if start is None or len(values) < 2:
            continue
        low, high = min(values.values()), max(values.values())
        if high - low > max(abs(high), abs(low)) * rel_tol + abs_tol:
            out.append(TagDivergence(start=start, end=end, values=dict(values)))
    return out


def interchangeable_tag_pairs(
    facts_by_tag: Mapping[str, Mapping[tuple[dt.date | None, dt.date], Fact]],
    *,
    rel_tol: float = 0.005,
    abs_tol: float = 2_000_000.0,
) -> frozenset[frozenset[str]]:
    """Tag pairs this filer demonstrably uses for the same thing.

    A pair qualifies only on evidence: they must overlap on at least one period
    and agree everywhere they overlap. Tags whose histories never touch are not
    interchangeable — there is nothing to check them against, and assuming
    equivalence is how two different measures end up summed together.
    """
    out: set[frozenset[str]] = set()
    tags = sorted(facts_by_tag)
    for i, left in enumerate(tags):
        for right in tags[i + 1 :]:
            shared = set(facts_by_tag[left]) & set(facts_by_tag[right])
            shared = {k for k in shared if k[0] is not None}
            if not shared:
                continue
            if all(
                abs(facts_by_tag[left][k].val - facts_by_tag[right][k].val)
                <= max(abs(facts_by_tag[left][k].val), abs(facts_by_tag[right][k].val)) * rel_tol + abs_tol
                for k in shared
            ):
                out.add(frozenset((left, right)))
    return frozenset(out)


@dataclass(frozen=True)
class Reconciliation:
    """Whether four derived quarters add back up to the reported fiscal year."""

    tag: str
    fiscal_year_end: dt.date
    annual: float
    quarters_sum: float
    quarter_ends: tuple[dt.date, ...]
    ok: bool

    @property
    def difference(self) -> float:
        return self.quarters_sum - self.annual

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "fiscal_year_end": self.fiscal_year_end.isoformat(),
            "annual": self.annual,
            "quarters_sum": self.quarters_sum,
            "difference": self.difference,
            "quarter_ends": [d.isoformat() for d in self.quarter_ends],
            "ok": self.ok,
        }


def reconcile_fiscal_years(
    quarters: Mapping[dt.date, PeriodValue],
    annuals: Mapping[dt.date, PeriodValue],
    *,
    rel_tol: float = 0.001,
    abs_tol: float = 2_000_000.0,
) -> list[Reconciliation]:
    """Check derived quarters against reported annuals, within one tag.

    Only fiscal years that four discrete quarters tile exactly — contiguous, no
    gaps, ending on the year end and starting on the year start — are checked. A
    failure is nearly always a restated annual sitting above unrestated quarters
    (Merck's FY2020 Organon spin-off, Becton Dickinson's Embecta separation), so
    it is surfaced as a flag rather than treated as an error.
    """
    out: list[Reconciliation] = []
    for year_end, annual in sorted(annuals.items()):
        if annual.start is None:
            continue
        parts: list[PeriodValue] = []
        cursor = year_end
        while cursor > annual.start and len(parts) < 4:
            quarter = quarters.get(cursor)
            if quarter is None or quarter.tag != annual.tag:
                break
            parts.append(quarter)
            cursor = quarter.start - dt.timedelta(days=1)
        if len(parts) != 4 or cursor != annual.start - dt.timedelta(days=1):
            continue

        total = sum(p.val for p in parts)
        tolerance = max(abs(annual.val) * rel_tol, abs_tol)
        out.append(
            Reconciliation(
                tag=annual.tag,
                fiscal_year_end=year_end,
                annual=annual.val,
                quarters_sum=total,
                quarter_ends=tuple(sorted(p.end for p in parts)),
                ok=abs(total - annual.val) <= tolerance,
            )
        )
    return out


@dataclass(frozen=True)
class QuarterlySeries:
    """Discrete quarterly values for one concept, plus how they were obtained."""

    concept: str
    resolution: ConceptResolution
    values: tuple[PeriodValue, ...]
    reconciliations: tuple[Reconciliation, ...] = ()
    divergences: tuple[TagDivergence, ...] = ()
    #: Tag pairs this filer demonstrably uses interchangeably, from
    #: `interchangeable_tag_pairs`. A figure aggregated across quarters may span
    #: several tags only if every pair among them appears here.
    interchangeable: frozenset[frozenset[str]] = frozenset()
    #: Period ends whose value was derived from a period the chain tags disagree
    #: about. The figure is still reported — it is the filer's own arithmetic —
    #: but it should carry a footnote rather than be read at face value.
    suspect_ends: frozenset[dt.date] = frozenset()
    flags: tuple[str, ...] = ()

    def by_end(self) -> dict[dt.date, PeriodValue]:
        return {v.end: v for v in self.values}

    def latest(self, n: int = 1) -> tuple[PeriodValue, ...]:
        return self.values[-n:] if n else ()

    def trailing_twelve_months(self, as_of: dt.date | None = None) -> PeriodValue | None:
        """Sum the four contiguous quarters ending at `as_of` (default: the latest).

        Returns None unless four quarters tile the window exactly. Where the
        window spans more than one tag — Moderna's revenue moves from `Revenues`
        to `RevenueFromContractWithCustomerExcludingAssessedTax` partway through
        2022 — the tags must first have been shown interchangeable for this
        filer. Otherwise the sum would add two different definitions together and
        report the result as one year of revenue.

        A single-tag window is returned even when one of its quarters is in
        `suspect_ends`. The arithmetic within one tag is the filer's own, so the
        figure is emitted and the series flag carries the caveat; refusing would
        drop several years of Pfizer revenue over a caveat rather than an error.
        A multi-tag window is held to the stricter test because it also has to
        assume two tags mean the same thing.
        """
        if not self.values:
            return None
        end = as_of or self.values[-1].end
        index = self.by_end()

        parts: list[PeriodValue] = []
        cursor = end
        for _ in range(4):
            quarter = index.get(cursor)
            if quarter is None:
                return None
            parts.append(quarter)
            cursor = quarter.start - dt.timedelta(days=1)

        window = (end - parts[-1].start).days + 1
        if not ANNUAL_DAYS[0] <= window <= ANNUAL_DAYS[1]:
            return None

        tags = {p.tag for p in parts}
        if len(tags) > 1:
            if any(p.end in self.suspect_ends for p in parts):
                return None
            if not all(
                frozenset((a, b)) in self.interchangeable
                for a in tags
                for b in tags
                if a != b
            ):
                return None

        ordered = tuple(t for t in self.resolution.chain if t in tags)
        return PeriodValue(
            concept=self.concept,
            tag=ordered[0],
            start=parts[-1].start,
            end=end,
            val=sum(p.val for p in parts),
            basis=Basis.DERIVED,
            filed=max(p.filed for p in parts),
            accns=tuple(dict.fromkeys(a for p in parts for a in p.accns)),
            forms=tuple(dict.fromkeys(f for p in parts for f in p.forms)),
            taxonomy=parts[0].taxonomy,
            unit=parts[0].unit,
            contributing_tags=ordered,
        )


def quarterly_series(
    companyfacts: Mapping[str, Any],
    concept: str | Concept,
    *,
    taxonomy: str = DEFAULT_TAXONOMY,
    unit: str = DEFAULT_UNIT,
    since: dt.date | None = None,
) -> QuarterlySeries:
    """Discrete quarterly values for one concept, resolved through its chain.

    Each tag in the chain is unwound to discrete quarters independently, then the
    results are merged in chain order: a period is filled by the first tag that
    covers it, so an earlier chain entry always wins where both are present and
    no value is ever the difference of two different tags.

    `since` trims the series to quarters ending on or after that date, and the
    flags describe the trimmed series. This matters: essentially every filer
    crossed the ASC 606 revenue transition around 2018, so a series carrying full
    history is "mixed tags" for all of them, and a flag that fires on the whole
    universe tells a reader nothing. Derivation still runs over every fact — only
    the reported window is narrowed.
    """
    concept = _lookup_concept(concept)
    if concept.kind is not ConceptKind.DURATION:
        raise UnsupportedConcept(
            f"{concept.name!r} is a {concept.kind.value} concept; M1 implements the "
            "duration concepts (revenue, R&D, operating cash flow) only"
        )

    merged: dict[dt.date, PeriodValue] = {}
    annuals: dict[str, dict[dt.date, PeriodValue]] = {}
    quarters_by_tag: dict[str, dict[dt.date, PeriodValue]] = {}
    observed_by_tag: dict[str, dict[tuple[dt.date | None, dt.date], Fact]] = {}
    available: list[str] = []

    for tag in concept.tags:
        facts = extract_facts(companyfacts, tag, taxonomy=taxonomy, unit=unit)
        if not facts:
            continue
        available.append(tag)
        observed_by_tag[tag] = latest_by_period(facts)
        tag_quarters = discrete_quarters(facts, concept=concept.name)
        quarters_by_tag[tag] = tag_quarters
        annuals[tag] = annual_totals(facts, concept=concept.name)
        for end, value in tag_quarters.items():
            merged.setdefault(end, value)  # chain order: first tag to cover a period wins

    values = tuple(
        sorted(
            (v for v in merged.values() if since is None or v.end >= since),
            key=lambda v: v.end,
        )
    )
    used = {v.tag for v in values}
    tags_used = tuple(tag for tag in concept.tags if tag in used)  # chain order, for determinism

    resolution = ConceptResolution(
        concept=concept.name,
        chain=concept.tags,
        tags_available=tuple(available),
        tags_used=tags_used,
        near_miss_tags=()
        if available
        else _near_misses(companyfacts, concept, taxonomy=taxonomy),
    )

    reconciliations = tuple(
        r
        for tag in tags_used
        for r in reconcile_fiscal_years(quarters_by_tag[tag], annuals.get(tag, {}))
        if since is None or r.fiscal_year_end >= since
    )

    divergences = tuple(
        d for d in detect_tag_divergence(observed_by_tag) if since is None or d.end >= since
    )
    interchangeable = interchangeable_tag_pairs(observed_by_tag)
    disputed = {(d.start, d.end) for d in divergences}
    suspect = frozenset(
        v.end for v in values if any(period in disputed for period in v.derived_from)
    )

    flags: list[str] = []
    if not available:
        flags.append(f"{concept.name}:{FLAG_NO_TAG_RESOLVED}")
    elif not values:
        flags.append(f"{concept.name}:{FLAG_NO_QUARTERS}")
    if resolution.uses_fallback:
        flags.append(f"{concept.name}:{FLAG_FALLBACK_TAG}")
    if resolution.mixed:
        flags.append(f"{concept.name}:{FLAG_MIXED_TAGS}")
    if any(not r.ok for r in reconciliations):
        flags.append(f"{concept.name}:{FLAG_FY_RECONCILIATION_FAILED}")
    if suspect:
        flags.append(f"{concept.name}:{FLAG_CHAIN_TAGS_DIVERGE}")

    return QuarterlySeries(
        concept=concept.name,
        resolution=resolution,
        values=values,
        reconciliations=reconciliations,
        divergences=divergences,
        interchangeable=interchangeable,
        suspect_ends=suspect,
        flags=tuple(flags),
    )


# --------------------------------------------------------------------------- #
# Table assembly
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class QuarterRow:
    """One quarter across every requested concept — the SPEC §7 `quarterly` shape."""

    period_start: dt.date
    period_end: dt.date
    values: Mapping[str, float | None]
    source_tags: Mapping[str, str | None]
    source_basis: Mapping[str, str | None]
    flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
        }
        row.update(self.values)
        row["source_tags"] = dict(self.source_tags)
        row["source_basis"] = dict(self.source_basis)
        if self.flags:
            row["flags"] = list(self.flags)
        return row


@dataclass(frozen=True)
class QuarterlyTable:
    """Every requested concept for one company, quarter by quarter."""

    cik: str | None
    entity_name: str | None
    series: Mapping[str, QuarterlySeries]
    rows: tuple[QuarterRow, ...]
    flags: tuple[str, ...] = field(default=())
    #: Every taxonomy the filing reports under, so an IFRS filer is diagnosable
    #: rather than just empty.
    taxonomies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cik": self.cik,
            "entity_name": self.entity_name,
            "taxonomies": list(self.taxonomies),
            "quarterly": [row.to_dict() for row in self.rows],
            "concepts": {
                name: {
                    "resolution": s.resolution.to_dict(),
                    "reconciliations": [r.to_dict() for r in s.reconciliations if not r.ok],
                    "tag_divergences": [d.to_dict() for d in s.divergences],
                }
                for name, s in self.series.items()
            },
            "data_quality_flags": list(self.flags),
        }


def build_quarterly_table(
    companyfacts: Mapping[str, Any],
    concepts: Sequence[str] = M1_CONCEPTS,
    *,
    taxonomy: str = DEFAULT_TAXONOMY,
    unit: str = DEFAULT_UNIT,
    since: dt.date | None = None,
) -> QuarterlyTable:
    """Assemble the per-quarter table for one company.

    Rows are keyed on period end, which is the axis every concept shares. Where
    concepts disagree on the period start — they should not, since one fiscal
    calendar governs all of them — the earliest is kept and the row is flagged.
    """
    series = {
        name: quarterly_series(companyfacts, name, taxonomy=taxonomy, unit=unit, since=since)
        for name in concepts
    }

    company_flags: list[str] = []
    node = companyfacts.get("facts", {})
    taxonomies = tuple(sorted(node)) if isinstance(node, Mapping) else ()
    if taxonomy not in taxonomies:
        company_flags.append(FLAG_NO_TAXONOMY)
    if series and not any(s.resolution.tags_available for s in series.values()):
        # A foreign private issuer filing 20-F under `ifrs-full` lands here, as
        # does a filer that simply reports none of the requested concepts. The
        # taxonomy list on the table tells the two apart.
        company_flags.append(FLAG_NO_CONCEPTS_RESOLVED)
    for s in series.values():
        company_flags.extend(s.flags)

    indexed = {name: s.by_end() for name, s in series.items()}
    ends = sorted({end for index in indexed.values() for end in index})

    rows: list[QuarterRow] = []
    for end in ends:
        present = [index[end] for index in indexed.values() if end in index]
        starts = {v.start for v in present}
        row_flags = [] if len(starts) == 1 else [FLAG_PERIOD_START_MISMATCH]
        row_flags += [
            f"{name}:{FLAG_TAG_BASIS_UNCERTAIN}"
            for name, s in series.items()
            if end in s.suspect_ends
        ]
        rows.append(
            QuarterRow(
                period_start=min(starts),
                period_end=end,
                values={name: (indexed[name][end].val if end in indexed[name] else None) for name in concepts},
                source_tags={name: (indexed[name][end].tag if end in indexed[name] else None) for name in concepts},
                source_basis={
                    name: (indexed[name][end].basis.value if end in indexed[name] else None) for name in concepts
                },
                flags=tuple(row_flags),
            )
        )

    return QuarterlyTable(
        cik=str(companyfacts["cik"]).zfill(10) if companyfacts.get("cik") is not None else None,
        entity_name=companyfacts.get("entityName"),
        series=series,
        rows=tuple(rows),
        flags=tuple(dict.fromkeys(company_flags)),
        taxonomies=taxonomies,
    )
