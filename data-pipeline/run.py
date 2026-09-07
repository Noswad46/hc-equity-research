"""Pipeline orchestrator: fetch EDGAR, assemble fundamentals, write `src/data/`.

Produces the three artefacts in SPEC §7 — `meta.json`, `screener.json` and one
`companies/{TICKER}.json` per covered filer — and nothing else. Clinical and
regulatory data (SPEC §5.2, §5.3) are M4 and M7; their keys are emitted as null
rather than omitted, so the shape the site consumes never changes underneath it.

Two rules govern the output.

**Every key in the schema is always present.** A metric that is not computed yet
is `null`. A consumer can then distinguish "not implemented" from "computed as
zero" without having to know which milestone it is looking at.

**Numbers are emitted as the filer reported them.** SEC XBRL values are integers;
this module casts the float it carries internally back to `int` where the value
is integral, so nothing acquires a spurious `.0` on the way to disk. There is no
rounding, no scaling to millions, and no unit conversion anywhere in the
pipeline or the templates.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sources.edgar import Company, EdgarClient, load_universe
from transform.derive import GROWTH_FLOOR, all_metrics
from transform.fundamentals import (
    CONCEPT_CHAINS,

    M3_CONCEPTS,
    PERIODIC_FORMS,
    QuarterlySeries,
    annual_series,
    build_quarterly_table,
    extract_facts,
)

log = logging.getLogger("run")

PIPELINE_VERSION = "1.0.0"

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_UNIVERSE = HERE / "universe.yaml"
DEFAULT_CACHE = HERE / "cache"
DEFAULT_OUT = REPO_ROOT / "src" / "data"

#: SPEC §6 metrics computed from fundamentals alone, all live as of M3.
DERIVED_METRICS = (
    "operating_margin",
    "ocf_margin",
    "net_cash",
    "cash_runway_quarters",
    "rnd_intensity",
)

#: SPEC §5.2 / §5.3. Whole sections, not yet built.
UNCOMPUTED_PIPELINE_METRICS = (
    "active_trials",
    "phase_3_trials",
    "pipeline_depth_score",
    "pipeline_concentration",
    "clinical_momentum",
)


# --------------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------------- #


def number(value: float | None) -> int | float | None:
    """Emit an integral float as an int, so no figure gains a spurious `.0`.

    XBRL monetary facts are integers. The float lives inside this pipeline only
    because arithmetic on quarters is easier that way; it should not reach disk.
    """
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def iso(value: dt.date | None) -> str | None:
    return value.isoformat() if value else None


# --------------------------------------------------------------------------- #
# Data-quality records
# --------------------------------------------------------------------------- #


def quality_records(series_by_concept: Mapping[str, QuarterlySeries]) -> list[dict[str, Any]]:
    """Flatten every flag into a record carrying the period it applies to.

    Emitted structured rather than pre-worded: the code and its context travel in
    the JSON, and the presentation layer turns them into sentences. That keeps
    one wording in one place, and keeps the data file free of prose that would
    have to be re-checked every time it changed.
    """
    out: list[dict[str, Any]] = []

    def add(code: str, concept: str, **fields: Any) -> None:
        record = {"code": code, "concept": concept, "period_start": None, "period_end": None}
        record.update(fields)
        out.append(record)

    for name, series in series_by_concept.items():
        resolution = series.resolution

        if not resolution.tags_available:
            add(
                "no_tag_resolved",
                name,
                detail={"chain": list(resolution.chain), "near_misses": list(resolution.near_miss_tags)},
            )
            continue
        if not series.values:
            add("no_quarters_derived", name, detail={"tags_available": list(resolution.tags_available)})
            continue

        if series.is_stale:
            add(
                "stale_series",
                name,
                period_end=iso(series.latest_period_end),
                detail={
                    "latest_period_end": iso(series.latest_period_end),
                    "reference_period_end": iso(series.reference_period_end),
                    "days_behind": series.staleness_days,
                    "tag": series.values[-1].tag,
                },
            )

        for cutover in series.cutovers:
            add(
                "basis_cutover",
                name,
                period_end=cutover.first_end_after.isoformat(),
                detail=cutover.to_dict(),
            )

        for reconciliation in series.reconciliations:
            if reconciliation.ok:
                continue
            add(
                "fy_reconciliation_failed",
                name,
                period_end=reconciliation.fiscal_year_end.isoformat(),
                detail=reconciliation.to_dict(),
            )

        for divergence in series.divergences:
            add(
                "chain_tags_diverge",
                name,
                period_start=divergence.start.isoformat(),
                period_end=divergence.end.isoformat(),
                detail=divergence.to_dict(),
            )

        for value in series.values:
            for flag in value.flags:
                add(
                    flag,
                    name,
                    period_start=value.start.isoformat(),
                    period_end=value.end.isoformat(),
                    detail={"tag": value.tag, "measurement_basis": value.measurement_basis},
                )

        for dropped in series.dropped_overlaps:
            add(
                "overlapping_periods",
                name,
                period_start=dropped.start.isoformat(),
                period_end=dropped.end.isoformat(),
                detail={"tag": dropped.tag, "value": number(dropped.val)},
            )

        spans = {t: [iso(a), iso(b)] for t, (a, b) in series.tag_spans.items()}
        if resolution.uses_fallback:
            add(
                "fallback_tag",
                name,
                detail={
                    "primary_tag": resolution.primary_tag,
                    "tags_used": list(resolution.tags_used),
                    "tag_spans": spans,
                },
            )
        if len(resolution.tags_used) > 1:
            add("mixed_tags", name, detail={"tag_spans": spans})
        if len(series.measurement_bases) > 1:
            add(
                "mixed_measurement_basis",
                name,
                detail={"bases": [s.to_dict() for s in series.segments]},
            )

    return out


# --------------------------------------------------------------------------- #
# Filings
# --------------------------------------------------------------------------- #


def source_filings(
    companyfacts: Mapping[str, Any], cik: str, used_accns: Iterable[str]
) -> list[dict[str, Any]]:
    """The filings the figures on the page actually came from.

    Scoped to accessions that produced an emitted value, rather than the filer's
    whole history, so every link on a company page corresponds to a number on it.
    """
    wanted = set(used_accns)
    seen: dict[str, dict[str, Any]] = {}

    for concept in CONCEPT_CHAINS.values():
        for tag in concept.tags:
            for fact in extract_facts(
                companyfacts, tag, duration_only=False, forms=PERIODIC_FORMS
            ):
                if fact.accn not in wanted or fact.accn in seen:
                    continue
                bare = fact.accn.replace("-", "")
                seen[fact.accn] = {
                    "accession": fact.accn,
                    "form": fact.form,
                    "filed": fact.filed.isoformat(),
                    "url": (
                        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{bare}/{fact.accn}-index.htm"
                    ),
                }

    return sorted(seen.values(), key=lambda f: (f["filed"], f["accession"]), reverse=True)


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


def period_rows(
    series_by_concept: Mapping[str, QuarterlySeries],
    concepts: Sequence[str],
    *,
    restrict_to: Iterable[dt.date] | None = None,
    growth_from: QuarterlySeries | None = None,
) -> list[dict[str, Any]]:
    """One row per period end, across every concept, in SPEC §7's `quarterly` shape.

    `restrict_to` bounds which period ends become rows. The annual table needs it:
    a balance-sheet concept has no notion of a fiscal year, so cash is reported at
    every quarter end, and without a restriction each of those would open an
    annual row whose flow columns were all null.
    """
    indexed = {name: series_by_concept[name].by_end() for name in concepts}
    ends = sorted({end for index in indexed.values() for end in index})
    if restrict_to is not None:
        allowed = set(restrict_to)
        ends = [end for end in ends if end in allowed]

    rows: list[dict[str, Any]] = []
    for end in ends:
        present = [index[end] for index in indexed.values() if end in index]
        # Instant concepts start and end on the same day; they must not drag the
        # row's period start forward onto the balance-sheet date.
        starts = [v.start for v in present if v.start != v.end] or [v.start for v in present]
        row: dict[str, Any] = {
            "period_start": min(starts).isoformat(),
            "period_end": end.isoformat(),
        }
        for name in concepts:
            value = indexed[name].get(end)
            row[name] = number(value.val) if value else None
        row["source_tags"] = {n: (indexed[n][end].tag if end in indexed[n] else None) for n in concepts}
        row["source_basis"] = {
            n: (indexed[n][end].basis.value if end in indexed[n] else None) for n in concepts
        }
        row["measurement_basis"] = {
            n: (indexed[n][end].measurement_basis if end in indexed[n] else None) for n in concepts
        }
        row["flags"] = sorted(
            {f"{n}:{flag}" for n in concepts if end in indexed[n] for flag in indexed[n][end].flags}
        )
        if growth_from is not None:
            # Growth as at this period end, so a suppressed year is visible on the
            # row it belongs to rather than only in the latest headline figure.
            row["revenue_growth_yoy"] = growth_from.growth(end).to_dict()
        rows.append(row)
    return rows


def screener_record(
    company: Company,
    series_by_concept: Mapping[str, QuarterlySeries],
    flags: Sequence[str],
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The flat per-company record for SPEC §7's `screener.json`."""
    revenue = series_by_concept["revenue"]
    metrics = metrics or {}

    def ttm(name: str) -> int | float | None:
        series = series_by_concept.get(name)
        value = series.trailing_twelve_months() if series else None
        return number(value.val) if value else None

    cash_series = series_by_concept.get("cash")
    latest_cash = cash_series.values[-1] if cash_series and cash_series.values else None

    record: dict[str, Any] = {
        "ticker": company.ticker,
        "cik": company.cik,
        "name": company.name,
        "subsector": company.subsector,
        "therapeutic_focus": list(company.therapeutic_focus),
        "fiscal_period_end": iso(revenue.latest_period_end),
        "revenue_ttm": ttm("revenue"),
        "rnd_ttm": ttm("rnd"),
        "ocf_ttm": ttm("ocf"),
        "operating_income_ttm": ttm("operating_income"),
        "cash": number(latest_cash.val) if latest_cash else None,
    }

    # Derived metrics travel with the reasons they are null, so the screener can
    # show "n/m" or a suppression note rather than an unexplained blank.
    record["revenue_growth_yoy"] = metrics.get("revenue_growth_yoy")
    for key in DERIVED_METRICS:
        record[key] = metrics.get(key)

    for key in UNCOMPUTED_PIPELINE_METRICS:
        record[key] = None
    record["data_quality_flags"] = list(flags)
    return record


def company_document(
    company: Company,
    companyfacts: Mapping[str, Any],
    concepts: Sequence[str] = M3_CONCEPTS,
) -> dict[str, Any]:
    """The full per-company record: SPEC §7's screener fields plus the detail."""
    table = build_quarterly_table(companyfacts, concepts)
    quarterly = table.series
    annual = {name: annual_series(companyfacts, name, quarterly=quarterly[name]) for name in concepts}

    # Fiscal year ends come from the flow concepts, which are the only ones that
    # have a fiscal year. Balances are then read at those dates.
    year_ends = {
        value.end
        for name in concepts
        if CONCEPT_CHAINS[name].kind.value == "duration"
        for value in annual[name].values
    }

    metrics = {name: result.to_dict() for name, result in all_metrics(quarterly).items()}
    document = screener_record(company, quarterly, table.flags, metrics)

    used_accns = {
        accn
        for group in (quarterly, annual)
        for series in group.values()
        for value in series.values
        for accn in value.accns
    }

    document.update(
        {
            "entity_name": table.entity_name,
            "taxonomies": list(table.taxonomies),
            "quarterly": period_rows(quarterly, concepts, growth_from=quarterly["revenue"]),
            "annual": period_rows(
                annual, concepts, restrict_to=year_ends, growth_from=quarterly["revenue"]
            ),
            "concepts": {
                name: {
                    "label": CONCEPT_CHAINS[name].label,
                    "kind": CONCEPT_CHAINS[name].kind.value,
                    "candidates": list(CONCEPT_CHAINS[name].tags),
                    "selection": CONCEPT_CHAINS[name].selection.value,
                    "tags_available": list(quarterly[name].resolution.tags_available),
                    "tags_used": list(quarterly[name].resolution.tags_used),
                    "primary_tag": quarterly[name].resolution.primary_tag,
                    "uses_fallback": quarterly[name].resolution.uses_fallback,
                    "measurement_bases": list(quarterly[name].measurement_bases),
                    "basis_segments": [s.to_dict() for s in quarterly[name].segments],
                    "basis_cutovers": [c.to_dict() for c in quarterly[name].cutovers],
                    "latest_period_end": iso(quarterly[name].latest_period_end),
                    "reference_period_end": iso(quarterly[name].reference_period_end),
                    "staleness_days": quarterly[name].staleness_days,
                    "is_stale": quarterly[name].is_stale,
                    "growth_yoy": quarterly[name].growth().to_dict(),
                }
                for name in concepts
            },
            "data_quality": quality_records(quarterly),
            "filings": source_filings(companyfacts, company.cik, used_accns),
            "pipeline": None,
            "regulatory": None,
        }
    )
    return document


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def write_json(path: Path, payload: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=1, sort_keys=False, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def run(
    *,
    universe_path: Path,
    out_dir: Path,
    cache_dir: Path | None,
    user_agent: str | None,
    refresh: bool,
    now: dt.datetime,
) -> int:
    companies = load_universe(universe_path)
    client = EdgarClient(user_agent=user_agent, cache_dir=cache_dir)

    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    screener: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []

    companies_dir = out_dir / "companies"
    companies_dir.mkdir(parents=True, exist_ok=True)

    for company, facts, error in client.iter_companyfacts(companies, refresh=refresh):
        if error is not None or facts is None:
            # SPEC §10: a failure on one company must not fail the run.
            failed.append({"ticker": company.ticker, "cik": company.cik, "error": str(error)})
            log.warning("%s failed: %s", company.ticker, error)
            continue

        document = company_document(company, facts)
        size = write_json(companies_dir / f"{company.ticker}.json", document)
        screener.append(_screener_view(document))
        log.info("%-6s %6.1f KB  %3d quarters", company.ticker, size / 1024, len(document["quarterly"]))

    write_json(out_dir / "screener.json", {"generated_at": generated_at, "companies": screener})
    write_json(
        out_dir / "meta.json",
        {
            "generated_at": generated_at,
            "universe_size": len(companies),
            "sources": {
                "edgar": {
                    "fetched_at": generated_at,
                    "companies_ok": len(screener),
                    "companies_failed": failed,
                },
                "clinicaltrials": None,
                "openfda": None,
            },
            "pipeline_version": PIPELINE_VERSION,
            "thresholds": {"growth_floor_usd": GROWTH_FLOOR},
        },
    )

    log.info("wrote %d/%d companies to %s", len(screener), len(companies), out_dir)
    return 1 if failed else 0


#: Keys that belong in the flat screener record. Derived from the document so the
#: two can never drift apart.
_SCREENER_KEYS = (
    "ticker",
    "cik",
    "name",
    "subsector",
    "therapeutic_focus",
    "fiscal_period_end",
    "revenue_ttm",
    "revenue_growth_yoy",
    "rnd_ttm",
    "ocf_ttm",
    "operating_income_ttm",
    "cash",
    *DERIVED_METRICS,
    *UNCOMPUTED_PIPELINE_METRICS,
    "data_quality_flags",
)


def _screener_view(document: Mapping[str, Any]) -> dict[str, Any]:
    return {key: document[key] for key in _SCREENER_KEYS}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--user-agent", default=None, help="defaults to $SEC_USER_AGENT")
    parser.add_argument("--refresh", action="store_true", help="ignore cached EDGAR responses")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return run(
        universe_path=args.universe,
        out_dir=args.out,
        cache_dir=args.cache_dir,
        user_agent=args.user_agent,
        refresh=args.refresh,
        now=dt.datetime.now(dt.timezone.utc),
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
