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

from sources.clinicaltrials import (
    ClinicalTrialsClient,
    ClinicalTrialsError,
    EmptyPipelineError,
    Study,
)
from sources.edgar import Company, EdgarClient, load_universe
from transform.clinical import Pipeline, all_pipeline_metrics, is_active, summarise
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

#: How many consecutive failed refreshes a company may be carried through on its
#: last good figures before it is dropped from the site altogether.
#:
#: Carrying a stale row forward is the right answer to one bad fetch. Carrying it
#: forever is a different failure, and a worse one: at the weekly cadence in
#: SPEC §10 this is about a month, after which a company that still will not
#: fetch is broken rather than briefly unavailable. Month-old figures sitting
#: under a current as-of date are exactly the stale-but-plausible output the
#: staleness guard on tag series exists to prevent, so past this bound the
#: company is reported missing instead.
MAX_STALE_RUNS = 4

#: Share of the universe that may fail before the run is worth waking someone
#: for. Alerting only. SPEC §10's rule is that the run still writes what it has,
#: and the workflow commits whatever landed regardless of this number.
ALERT_FAILURE_SHARE = 0.1

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_UNIVERSE = HERE / "universe.yaml"
DEFAULT_CACHE = HERE / "cache"
DEFAULT_OUT = REPO_ROOT / "src" / "data"

#: SPEC §6 metrics computed from fundamentals alone, all live as of M3.
DERIVED_METRICS = (
    "net_margin",
    "ocf_margin",
    "operating_margin",
    "net_cash",
    "cash_runway_quarters",
    "rnd_intensity",
)

#: SPEC §6 pipeline metrics, live as of M4.
PIPELINE_METRICS = (
    "pipeline_depth_score",
    "pipeline_concentration",
    "clinical_momentum",
    "discontinuation_rate",
    "rnd_per_late_stage_programme",
)

#: Plain counts that sit alongside them in the screener record.
PIPELINE_COUNTS = ("active_trials", "phase_3_trials")

#: SPEC §5.3. openFDA is M7.
UNCOMPUTED_REGULATORY = ()


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
    pipeline: Pipeline | None = None,
    pipeline_metrics: Mapping[str, Any] | None = None,
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
        "net_income_ttm": ttm("net_income"),
        "cash": number(latest_cash.val) if latest_cash else None,
    }

    # Derived metrics travel with the reasons they are null, so the screener can
    # show "n/m" or a suppression note rather than an unexplained blank.
    record["revenue_growth_yoy"] = metrics.get("revenue_growth_yoy")
    for key in DERIVED_METRICS:
        record[key] = metrics.get(key)

    record["active_trials"] = pipeline.active_trials_total if pipeline else None
    record["phase_3_trials"] = pipeline.by_phase.get("phase_3") if pipeline else None
    for key in PIPELINE_METRICS:
        record[key] = (pipeline_metrics or {}).get(key)
    record["data_quality_flags"] = list(flags)
    return record


def company_document(
    company: Company,
    companyfacts: Mapping[str, Any],
    concepts: Sequence[str] = M3_CONCEPTS,
    studies: Sequence[Study] | None = None,
    as_of: dt.date | None = None,
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

    pipeline = None
    pipeline_metrics: dict[str, Any] = {}
    if studies is not None:
        pipeline = summarise(
            studies, as_of=as_of or dt.date.today(), sponsors=company.ct_sponsor_names
        )
        pipeline_metrics = {
            name: result.to_dict()
            for name, result in all_pipeline_metrics(
                studies, pipeline, quarterly.get("rnd"), company.subsector
            ).items()
        }

    document = screener_record(
        company, quarterly, table.flags, metrics, pipeline, pipeline_metrics
    )

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
            "pipeline": pipeline.to_dict() if pipeline else None,
            # Active trials only. The aggregates above already summarise the
            # full history, and carrying every completed study since 1990 put
            # 2,740 records and 1.4 MB into Pfizer's page for nothing.
            "active_trials_detail": (
                [s.to_dict() for s in studies if is_active(s)] if studies is not None else None
            ),
            "regulatory": None,
            # Null on every document this function produces: a company that was
            # just fetched is by definition not stale. `run` stamps a block here
            # on the files it carries forward instead of rewriting.
            "stale": None,
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


# --------------------------------------------------------------------------- #
# Carrying a failed company forward
# --------------------------------------------------------------------------- #


def _previous_state(out_dir: Path) -> tuple[dict[str, dict[str, Any]], str | None]:
    """The screener rows currently on disk, by ticker, and when they were written.

    Read before anything in this run is written, so it is the state the site is
    actually serving rather than the half-finished state this run is producing.
    A missing or unreadable file is not an error: it means there is nothing to
    carry forward, which is the correct answer on a first run.
    """
    path = out_dir / "screener.json"
    if not path.exists():
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("previous screener.json unreadable (%s); nothing to carry forward", exc)
        return {}, None
    rows = {row["ticker"]: row for row in payload.get("companies", []) if "ticker" in row}
    return rows, payload.get("generated_at")


def _aged(previous: Mapping[str, Any], *, reason: str, last_good: str | None) -> dict[str, Any] | None:
    """Age a company's last good row by one failed run, or give up on it.

    Returns the row to re-emit with its `stale` block advanced, or `None` once
    it has been carried `MAX_STALE_RUNS` times and should be dropped instead.
    """
    was = previous.get("stale") or {}
    consecutive = int(was.get("consecutive_failures", 0)) + 1
    if consecutive > MAX_STALE_RUNS:
        return None

    row = dict(previous)
    row["stale"] = {
        # Set on the first failure and preserved through the rest, so it keeps
        # naming the run that last actually fetched this company rather than
        # creeping forward one week at a time.
        "last_success_at": was.get("last_success_at") or last_good,
        "consecutive_failures": consecutive,
        "limit": MAX_STALE_RUNS,
        "error": reason,
    }
    return row


def _mark_stale(path: Path, stale: Mapping[str, Any]) -> bool:
    """Stamp the stale block onto a company file this run did not rewrite.

    The figures inside stay exactly as the last good run produced them; only the
    marker changes, so the page can say how old they are instead of presenting
    them under the current as-of date. Returns False when there is no file to
    mark, in which case the screener row would link to a page that is not there.
    """
    if not path.exists():
        return False
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("%s unreadable (%s); not carried forward", path.name, exc)
        return False
    document["stale"] = dict(stale)
    write_json(path, document)
    return True


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
    ctgov = ClinicalTrialsClient(
        cache_dir=(cache_dir / "ctgov") if cache_dir else None
    )
    trials_as_of = now.date()

    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    previous_rows, previous_generated_at = _previous_state(out_dir)

    screener: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    carried: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    fetched = 0
    studies_indexed = 0

    companies_dir = out_dir / "companies"
    companies_dir.mkdir(parents=True, exist_ok=True)

    def handle_failure(company: Company, reason: str) -> None:
        """SPEC §10: one company failing must not fail the run — and must not
        quietly remove the company from the site either.

        The last good row is re-emitted with a stale marker for up to
        `MAX_STALE_RUNS` refreshes. Past that, or with nothing good to fall back
        on, the company is dropped and its page removed, so the site says
        "missing" rather than showing month-old figures as current.
        """
        failed.append({"ticker": company.ticker, "cik": company.cik, "error": reason})
        document_path = companies_dir / f"{company.ticker}.json"
        previous = previous_rows.get(company.ticker)

        row = (
            _aged(previous, reason=reason, last_good=previous_generated_at)
            if previous is not None
            else None
        )
        if row is not None and not _mark_stale(document_path, row["stale"]):
            # A row with no page behind it is worse than no row.
            row = None

        if row is None:
            why = (
                "no previous record"
                if previous is None
                else f"stale for more than {MAX_STALE_RUNS} refreshes"
            )
            dropped.append(
                {
                    "ticker": company.ticker,
                    "cik": company.cik,
                    "error": reason,
                    "dropped_because": why,
                }
            )
            document_path.unlink(missing_ok=True)
            log.warning("%-6s dropped (%s): %s", company.ticker, why, reason)
            return

        stale = row["stale"]
        screener.append(row)
        carried.append(
            {
                "ticker": company.ticker,
                "last_success_at": stale["last_success_at"],
                "consecutive_failures": stale["consecutive_failures"],
            }
        )
        log.warning(
            "%-6s stale %d/%d, figures from %s: %s",
            company.ticker,
            stale["consecutive_failures"],
            MAX_STALE_RUNS,
            stale["last_success_at"],
            reason,
        )

    for company, facts, error in client.iter_companyfacts(companies, refresh=refresh):
        if error is not None or facts is None:
            handle_failure(company, str(error))
            continue

        try:
            studies = ctgov.studies_for_company(
                company.ct_sponsor_names,
                exclusions=company.ct_sponsor_exclusions,
                ticker=company.ticker,
                refresh=refresh,
            )
        except EmptyPipelineError:
            # A company with sponsor strings that returns nothing is a broken
            # mapping, not a company without trials. SPEC §10's resilience rule
            # covers a source being down; it does not cover a silent zero.
            raise
        except ClinicalTrialsError as exc:
            handle_failure(company, str(exc))
            continue

        fetched += 1
        document = company_document(
            company, facts, studies=studies, as_of=trials_as_of
        )
        size = write_json(companies_dir / f"{company.ticker}.json", document)
        studies_indexed += len(studies)
        screener.append(_screener_view(document))
        log.info(
            "%-6s %6.1f KB  %3d quarters  %4d trials (%d active)",
            company.ticker,
            size / 1024,
            len(document["quarterly"]),
            len(studies),
            document["active_trials"] or 0,
        )

    # Universe order, so a carried-forward row sits where it always sat rather
    # than migrating to the end of the file and showing up as a spurious diff.
    order = {company.ticker: i for i, company in enumerate(companies)}
    screener.sort(key=lambda row: order.get(row["ticker"], len(order)))

    write_json(out_dir / "screener.json", {"generated_at": generated_at, "companies": screener})
    write_json(
        out_dir / "meta.json",
        {
            "generated_at": generated_at,
            "universe_size": len(companies),
            "sources": {
                "edgar": {
                    "fetched_at": generated_at,
                    # Freshly fetched this run. Deliberately not the row count:
                    # the home page reports this as "n of m filers", and a
                    # carried-forward row is not a filer that was reached.
                    "companies_ok": fetched,
                    "companies_failed": failed,
                    "companies_carried_stale": carried,
                    "companies_dropped": dropped,
                },
                "clinicaltrials": {
                    "fetched_at": generated_at,
                    "studies_indexed": studies_indexed,
                    "as_of": trials_as_of.isoformat(),
                },
                "openfda": None,
            },
            "pipeline_version": PIPELINE_VERSION,
            "thresholds": {
                "growth_floor_usd": GROWTH_FLOOR,
                "max_stale_runs": MAX_STALE_RUNS,
                "alert_failure_share": ALERT_FAILURE_SHARE,
            },
        },
    )

    log.info(
        "wrote %d rows to %s — %d fetched, %d carried stale, %d dropped",
        len(screener),
        out_dir,
        fetched,
        len(carried),
        len(dropped),
    )
    # Non-zero marks the run for a human to look at. It does not decide whether
    # the data is committed: the workflow commits what landed either way, so a
    # flaky fetch costs visibility, not a week of fresh figures.
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
    "net_income_ttm",
    "cash",
    *DERIVED_METRICS,
    *PIPELINE_COUNTS,
    *PIPELINE_METRICS,
    "data_quality_flags",
    # Null on a freshly fetched row; a block naming the last good run on one
    # carried forward through a failed refresh.
    "stale",
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
