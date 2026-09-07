"""Discover the exact ClinicalTrials.gov lead-sponsor strings for the universe.

SPEC §4 is explicit that sponsor names cannot be fuzzy-matched: subsidiaries file
under their own names for years after an acquisition, and a wrong mapping
attributes the wrong pipeline to the wrong company while looking entirely
plausible. This tool therefore *proposes nothing*. It runs a set of queries,
reports every distinct lead sponsor those queries surface, and leaves the mapping
to a human. It writes nothing into `universe.yaml`.

Keep it — it reruns whenever tickers are added.

Two properties of the ClinicalTrials.gov search shape everything here.

**It matches whole tokens, not substrings.** `query.spons=Moderna` returns a
single unrelated study, because Moderna's lead-sponsor string is `ModernaTX, Inc.`
and `Moderna` is not a token of `ModernaTX`. A company can therefore be entirely
invisible to a query on its own name. Where that happens the tool raises a
discovery gap rather than quietly reporting nothing, because a silent zero is
indistinguishable from a company with no trials.

**`query.spons` matches collaborators too.** A discovery query on `Pfizer`
returns thousands of studies led by universities that merely list Pfizer as a
collaborator. That is useful for discovery — it is how subsidiary names surface —
but it means counts from a discovery query are meaningless. Every count in the
report is measured separately with an exact whole-field match.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
PIPELINE_ROOT = HERE.parent
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

import requests  # noqa: E402

from sources.edgar import RateLimiter, load_universe  # noqa: E402

log = logging.getLogger("enumerate_sponsors")

BASE = "https://clinicaltrials.gov/api/v2/studies"
PAGE_SIZE = 1000

#: ClinicalTrials.gov publishes no rate limit. Three a second is well within what
#: a public endpoint should tolerate and keeps a full run under a minute.
REQUESTS_PER_SECOND = 3.0

#: SPEC §5.2: interventional only, or counts are inflated by investigator-initiated
#: work. Applied to discovery as well as measurement so the two agree.
INTERVENTIONAL = "AREA[StudyType]INTERVENTIONAL"

#: Only these fields are requested. The full record averages 17 kB; this is a
#: fraction of that, and the run fetches tens of thousands of studies.
FIELDS = "NCTId,BriefTitle,LeadSponsorName,OverallStatus,StartDate,StudyType"

#: Subsidiaries worth querying explicitly. Acquisitions are the hard case: trials
#: stay under the acquired entity's name for years, so the parent's name never
#: surfaces them.
CANDIDATE_SUBSIDIARIES: Mapping[str, tuple[str, ...]] = {
    "PFE": (
        "Wyeth",
        "Hospira",
        "Array BioPharma",
        "Medivation",
        "Arena Pharmaceuticals",
        "Biohaven",
        "Seagen",
        "Global Blood Therapeutics",
    ),
    "JNJ": (
        "Janssen Research & Development",
        "Janssen Biotech",
        "Janssen Vaccines & Prevention",
        "Janssen-Cilag",
        "Johnson & Johnson Innovative Medicine",
        "Actelion",
        "Abiomed",
        "Shockwave",
    ),
    "MRK": (
        "Merck Sharp & Dohme",
        "Acceleron Pharma",
        "Prometheus Biosciences",
        "Pandion Therapeutics",
        "Imago BioSciences",
        "Organon",
    ),
    "GILD": ("Kite Pharma", "Immunomedics", "Forty Seven", "CymaBay Therapeutics"),
    "BDX": ("C. R. Bard", "CareFusion", "Bard Peripheral Vascular"),
}

#: Query strings that no mechanical transformation of the registrant name would
#: produce, found by probing the API. Without `ModernaTX` here, Moderna's entire
#: pipeline is invisible to this tool.
KNOWN_ALIASES: Mapping[str, tuple[str, ...]] = {
    "MRNA": ("ModernaTX",),
}

#: Strings that must never be attributed to a covered company. Merck & Co (MRK)
#: and Merck KGaA of Darmstadt are unrelated listed companies that share a name;
#: outside North America the branding is reversed. Matching the bare token
#: "Merck" mixes their pipelines together.
FOREIGN_MERCK = re.compile(r"merck kgaa|emd serono|merck healthcare|darmstadt|merck serono", re.I)

#: J&J retired the Janssen brand for "Johnson & Johnson Innovative Medicine" in
#: 2024. Taking only one string makes the pipeline look like it collapsed.
JANSSEN_BRAND = re.compile(r"janssen", re.I)
JNJ_NEW_BRAND = re.compile(r"johnson\s*&\s*johnson innovative medicine", re.I)

#: Organon was spun out of Merck in 2021. Its trials are the clinical counterpart
#: of the FY2020 financial restatement already flagged in the fundamentals.
ORGANON = re.compile(r"organon", re.I)

_LEGAL_SUFFIX = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|plc|llc|l\.l\.c|ltd|limited|"
    r"sa|nv|ag|se|holdings|group|pharmaceuticals?|therapeutics|biosciences)\b\.?",
    re.I,
)
_PUNCT = re.compile(r"[^\w\s&-]")


def short_name(name: str) -> str:
    """`Becton, Dickinson and Company` -> `Becton, Dickinson`."""
    trimmed = _LEGAL_SUFFIX.sub("", name)
    trimmed = _PUNCT.sub(" ", trimmed)
    trimmed = re.sub(r"\band\b", " ", trimmed, flags=re.I)
    return re.sub(r"\s+", " ", trimmed).strip(" ,-")


#: Words shared by half the sponsors in the registry. Keying the shortlist on
#: these matches Pfizer's query against "VA Office of Research and Development",
#: which buries the real candidates under hundreds of academic collaborators.
#: Dropped for shortlisting only — nothing here affects what is queried or counted.
GENERIC_TOKENS = frozenset(
    """
    and the for inc llc ltd limited corp corporation company companies plc gmbh
    bhd pte kabushiki kaisha
    pharma pharmaceutical pharmaceuticals therapeutics biosciences bioscience
    sciences science biotechnology biotech biopharma biopharmaceuticals
    research development global international national regional worldwide
    health healthcare medical medicine medicines clinical care products product
    institute institutes university universities hospital hospitals college
    center centre centres foundation trust school division group holdings
    laboratories laboratory labs technologies technology solutions services
    vaccines vaccine prevention immunotherapy oncology diagnostics devices
    """.split()
)


def tokens(text: str) -> set[str]:
    """Lowercase word tokens of length 3+, for shortlisting only — never for mapping."""
    return {t for t in re.split(r"[^\w]+", text.lower()) if len(t) >= 3}


def distinctive(text: str) -> set[str]:
    """Tokens specific enough to be worth shortlisting on."""
    return tokens(text) - GENERIC_TOKENS


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


@dataclass
class CtGovClient:
    """Throttled, retrying, disk-cached reader for the ClinicalTrials.gov v2 API.

    Deliberately shaped like `sources.edgar.EdgarClient`. Phase 2 promotes this
    to `sources/clinicaltrials.py`; it lives here for now so the discovery step
    stands alone.
    """

    cache_dir: Path | None = None
    user_agent: str = "healthcare-equity-screener (contact via repository)"
    requests_per_second: float = REQUESTS_PER_SECOND
    max_retries: int = 4
    timeout: float = 60.0
    session: requests.Session = field(default_factory=requests.Session)
    _limiter: RateLimiter = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.session.headers.update({"User-Agent": self.user_agent, "Accept": "application/json"})
        self._limiter = RateLimiter(self.requests_per_second)
        if self.cache_dir is not None:
            self.cache_dir = Path(self.cache_dir)

    def _cache_path(self, params: Mapping[str, Any]) -> Path | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(
            json.dumps(params, sort_keys=True).encode("utf-8")
        ).hexdigest()[:20]
        return self.cache_dir / f"{key}.json"

    def get(self, params: Mapping[str, Any]) -> dict[str, Any]:
        path = self._cache_path(params)
        if path is not None and path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                log.warning("discarding unreadable cache entry %s", path)

        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._limiter.acquire()
            try:
                response = self.session.get(BASE, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last = exc
            else:
                if response.status_code == 200:
                    payload = response.json()
                    if path is not None:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        tmp = path.with_suffix(".tmp")
                        tmp.write_text(json.dumps(payload), encoding="utf-8")
                        tmp.replace(path)
                    return payload
                if response.status_code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(
                        f"ClinicalTrials.gov returned {response.status_code}: {response.text[:200]}"
                    )
                last = RuntimeError(f"HTTP {response.status_code}")
            if attempt < self.max_retries:
                time.sleep(min(16.0, 0.5 * 2**attempt))
        raise RuntimeError(f"giving up after {self.max_retries + 1} attempts: {last}")

    def studies(self, params: Mapping[str, Any], *, max_pages: int | None = None) -> list[dict]:
        """Every study matching `params`, following `pageToken` to the end."""
        out: list[dict] = []
        token: str | None = None
        pages = 0
        while True:
            page = dict(params)
            page.update({"pageSize": PAGE_SIZE, "fields": FIELDS})
            if token:
                page["pageToken"] = token
            payload = self.get(page)
            out.extend(payload.get("studies", []))
            token = payload.get("nextPageToken")
            pages += 1
            if not token or (max_pages is not None and pages >= max_pages):
                break
        return out

    def count(self, advanced: str) -> int:
        payload = self.get(
            {"filter.advanced": advanced, "pageSize": 1, "countTotal": "true", "fields": FIELDS}
        )
        return int(payload.get("totalCount", 0))


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def read_study(study: Mapping[str, Any]) -> dict[str, Any]:
    section = study.get("protocolSection", {})
    ident = section.get("identificationModule", {})
    status = section.get("statusModule", {})
    sponsors = section.get("sponsorCollaboratorsModule", {})
    return {
        "nct_id": ident.get("nctId"),
        "title": ident.get("briefTitle"),
        "lead_sponsor": (sponsors.get("leadSponsor") or {}).get("name"),
        "status": status.get("overallStatus"),
        "start": (status.get("startDateStruct") or {}).get("date"),
    }


def exact_filter(name: str) -> str:
    """Whole-field match on the lead sponsor, plus the interventional filter.

    `COVERAGE[FullMatch]` is what makes this exact. Without it the same query
    returns every sponsor whose name merely contains the tokens — for Moderna,
    113 studies rather than the 99 it actually leads.
    """
    escaped = name.replace('"', '\\"')
    return f'AREA[LeadSponsorName]COVERAGE[FullMatch]"{escaped}" AND {INTERVENTIONAL}'


@dataclass
class SponsorRecord:
    name: str
    found_by: set[str] = field(default_factory=set)
    seen_in_discovery: int = 0
    exact_count: int | None = None
    earliest_start: str | None = None
    latest_start: str | None = None
    sample_nct: str | None = None
    sample_title: str | None = None

    def observe(self, study: Mapping[str, Any], query: str) -> None:
        """Record that a discovery query surfaced this sponsor. Discovery only."""
        self.found_by.add(query)
        self.seen_in_discovery += 1

    def measure(self, client: "CtGovClient") -> None:
        """Count and date this sponsor from its own exact whole-field match.

        Dates must come from here rather than from the discovery pass. A
        discovery query returns whatever studies matched *it*, which for a
        sponsor like `Janssen Pharmaceutical K.K.` was a single study out of 95 —
        and a date range drawn from one observation would have made the Janssen
        handover unreadable, which is the one thing this report exists to show.
        """
        studies = [read_study(s) for s in client.studies({"filter.advanced": exact_filter(self.name)})]
        self.exact_count = len(studies)
        starts = sorted(s["start"] for s in studies if s.get("start"))
        self.earliest_start = starts[0] if starts else None
        self.latest_start = starts[-1] if starts else None
        if studies:
            newest = max(studies, key=lambda s: s.get("start") or "")
            self.sample_nct = newest["nct_id"]
            self.sample_title = newest["title"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead_sponsor": self.name,
            "exact_interventional_count": self.exact_count,
            "seen_in_discovery": self.seen_in_discovery,
            "earliest_start": self.earliest_start,
            "latest_start": self.latest_start,
            "sample_nct_id": self.sample_nct,
            "sample_title": self.sample_title,
            "found_by_queries": sorted(self.found_by),
        }


def discovery_queries(company, subsidiaries: Sequence[str], aliases: Sequence[str]) -> list[str]:
    """The strings this tool will search on, in the order it searches them."""
    candidates = [company.name, short_name(company.name), *aliases, *subsidiaries]
    seen: list[str] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in seen:
            seen.append(candidate)
    return seen


def enumerate_company(client: CtGovClient, company, *, measure: bool) -> dict[str, Any]:
    subsidiaries = CANDIDATE_SUBSIDIARIES.get(company.ticker, ())
    aliases = KNOWN_ALIASES.get(company.ticker, ())
    queries = discovery_queries(company, subsidiaries, aliases)

    records: dict[str, SponsorRecord] = {}
    per_query: dict[str, int] = {}

    for query in queries:
        studies = client.studies({"query.spons": query, "filter.advanced": INTERVENTIONAL})
        per_query[query] = len(studies)
        for raw in studies:
            study = read_study(raw)
            name = study["lead_sponsor"]
            if not name:
                continue
            records.setdefault(name, SponsorRecord(name)).observe(study, query)

    # Shortlisting decides only what gets an exact count and a place in the
    # human-readable report; the full list of every lead sponsor seen is written
    # to the JSON regardless. Nothing here assigns a sponsor to a company.
    query_tokens: set[str] = set()
    for query in queries:
        query_tokens |= distinctive(query)

    shortlisted = [
        record for record in records.values() if distinctive(record.name) & query_tokens
    ]
    shortlisted.sort(key=lambda r: (-r.seen_in_discovery, r.name))

    if measure:
        for record in shortlisted:
            try:
                record.measure(client)
            except RuntimeError as exc:
                log.warning("could not measure %r: %s", record.name, exc)

    # A company invisible to a query on its own name is the Moderna trap. Report
    # it: a silent zero looks the same as a company with no trials.
    own_tokens = distinctive(company.name) | distinctive(short_name(company.name))
    self_named = [r for r in shortlisted if distinctive(r.name) & own_tokens]
    plain_queries = [company.name, short_name(company.name)]
    plain_hits = sum(per_query.get(q, 0) for q in plain_queries)

    return {
        "ticker": company.ticker,
        "name": company.name,
        "queries_run": queries,
        "studies_returned_per_query": per_query,
        "discovery_gap": not self_named or plain_hits < 5,
        "shortlisted": [r.to_dict() for r in shortlisted],
        "other_lead_sponsors_seen": sorted(
            (
                {"lead_sponsor": r.name, "seen_in_discovery": r.seen_in_discovery}
                for r in records.values()
                if r not in shortlisted
            ),
            key=lambda r: (-r["seen_in_discovery"], r["lead_sponsor"]),
        ),
    }


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


def render_report(results: Sequence[Mapping[str, Any]], generated_at: str) -> str:
    lines: list[str] = []
    w = lines.append

    w("# ClinicalTrials.gov lead-sponsor enumeration")
    w("")
    w(f"Generated {generated_at}. Interventional studies only.")
    w("")
    w("**Nothing here has been written to `universe.yaml`.** These are candidates for review.")
    w("")
    w("`exact` is a whole-field match on the lead sponsor")
    w("(`AREA[LeadSponsorName]COVERAGE[FullMatch]`), which is what M4 will use to count.")
    w("`seen` is how many studies the broad discovery query returned for that sponsor, and is")
    w("inflated by collaborator matches — it is a discovery signal, not a count.")
    w("")

    # ----- traps ---------------------------------------------------------- #
    w("## Traps")
    w("")

    foreign = [
        (r["ticker"], s)
        for r in results
        for s in r["shortlisted"] + r["other_lead_sponsors_seen"]
        if FOREIGN_MERCK.search(s["lead_sponsor"])
    ]
    w("### 1. Merck & Co is not Merck KGaA")
    w("")
    if foreign:
        w("These strings belong to **Merck KGaA of Darmstadt**, a separate listed company, and")
        w("must be excluded explicitly from MRK:")
        w("")
        for ticker, s in foreign:
            count = s.get("exact_interventional_count")
            w(f"- `{s['lead_sponsor']}` — surfaced under **{ticker}**"
              + (f", {count} interventional studies" if count is not None else ""))
    else:
        w("No Merck KGaA or EMD Serono strings surfaced in these queries.")
    w("")
    w("Either way, never match on the bare token `Merck`: a `query.spons=Merck` discovery run")
    w("returns thousands of studies spanning both companies plus unrelated collaborators.")
    w("")

    w("### 2. The Janssen to Johnson & Johnson Innovative Medicine handover")
    w("")
    jnj = next((r for r in results if r["ticker"] == "JNJ"), None)
    if jnj:
        branded = [
            s
            for s in jnj["shortlisted"]
            if JANSSEN_BRAND.search(s["lead_sponsor"]) or JNJ_NEW_BRAND.search(s["lead_sponsor"])
        ]
        if branded:
            w("Date ranges per string, so the handover is visible. Taking only one side of it")
            w("would show a pipeline collapse that never happened:")
            w("")
            w("| Lead sponsor | Exact | Earliest start | Latest start |")
            w("|---|---:|---|---|")
            for s in sorted(branded, key=lambda s: s.get("latest_start") or ""):
                w(
                    f"| `{s['lead_sponsor']}` | {s.get('exact_interventional_count')} "
                    f"| {s.get('earliest_start')} | {s.get('latest_start')} |"
                )
        else:
            w("No Janssen or Innovative Medicine strings surfaced, which is itself suspicious.")
    w("")

    w("### 3. Organon")
    w("")
    organon = [
        (r["ticker"], s)
        for r in results
        for s in r["shortlisted"] + r["other_lead_sponsors_seen"]
        if ORGANON.search(s["lead_sponsor"])
    ]
    if organon:
        w("Organon was spun out of Merck in 2021, the clinical counterpart of the FY2020")
        w("financial restatement already flagged in the fundamentals. Surfaced as:")
        w("")
        for ticker, s in organon:
            count = s.get("exact_interventional_count")
            w(f"- `{s['lead_sponsor']}` — under **{ticker}**"
              + (f", {count} interventional studies" if count is not None else "")
              + (f", starts {s.get('earliest_start')} to {s.get('latest_start')}" if s.get("earliest_start") else ""))
    else:
        w("No Organon strings surfaced under the Merck queries.")
    w("")

    gaps = [r for r in results if r["discovery_gap"]]
    w("### 4. Companies invisible to a query on their own name")
    w("")
    if gaps:
        w("ClinicalTrials.gov matches whole tokens, so a registrant name can fail to find its")
        w("own trials. These need an explicit alias, and a silent zero here would look identical")
        w("to a company with no trials:")
        w("")
        for r in gaps:
            w(f"- **{r['ticker']}** ({r['name']}) — plain-name queries returned "
              f"{sum(r['studies_returned_per_query'].get(q, 0) for q in [r['name']])} studies")
    else:
        w("None. Every company was reachable from its registrant name or a seeded alias.")
    w("")

    # ----- per company ---------------------------------------------------- #
    w("## Candidates by company")
    w("")
    for r in results:
        w(f"### {r['ticker']} — {r['name']}")
        w("")
        w(f"Queries run: {', '.join('`' + q + '`' for q in r['queries_run'])}")
        w("")
        if not r["shortlisted"]:
            w("No lead sponsors surfaced sharing a token with any query string.")
            w("")
            continue
        w("| Lead sponsor | Exact | Seen | Earliest | Latest | Sample NCT |")
        w("|---|---:|---:|---|---|---|")
        for s in r["shortlisted"]:
            w(
                f"| `{s['lead_sponsor']}` | {s.get('exact_interventional_count')} "
                f"| {s['seen_in_discovery']} | {s.get('earliest_start')} "
                f"| {s.get('latest_start')} | {s.get('sample_nct_id')} |"
            )
        others = r["other_lead_sponsors_seen"]
        if others:
            w("")
            w(f"{len(others)} further lead sponsors appeared in the discovery results without")
            w("sharing a token with any query string — collaborator matches, mostly academic.")
            w("They are listed in the JSON alongside this report.")
        w("")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--universe", type=Path, default=PIPELINE_ROOT / "universe.yaml")
    parser.add_argument("--out-dir", type=Path, default=PIPELINE_ROOT / "sponsors")
    parser.add_argument("--cache-dir", type=Path, default=PIPELINE_ROOT / "cache" / "ctgov")
    parser.add_argument("--tickers", nargs="*", help="limit to these tickers")
    parser.add_argument("--no-measure", action="store_true", help="skip exact-count queries")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    companies = load_universe(args.universe)
    if args.tickers:
        wanted = {t.upper() for t in args.tickers}
        companies = [c for c in companies if c.ticker in wanted]

    client = CtGovClient(cache_dir=args.cache_dir)
    results = []
    for company in companies:
        log.info("enumerating %s (%s)", company.ticker, company.name)
        result = enumerate_company(client, company, measure=not args.no_measure)
        results.append(result)
        log.info(
            "  %d shortlisted, %d other lead sponsors seen%s",
            len(result["shortlisted"]),
            len(result["other_lead_sponsors_seen"]),
            "  [DISCOVERY GAP]" if result["discovery_gap"] else "",
        )

    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    json_path = args.out_dir / "sponsor-enumeration.json"
    json_path.write_text(
        json.dumps({"generated_at": generated_at, "companies": results}, indent=1) + "\n",
        encoding="utf-8",
    )
    report_path = args.out_dir / "sponsor-enumeration.md"
    report_path.write_text(render_report(results, generated_at), encoding="utf-8")

    log.info("wrote %s and %s", report_path, json_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
