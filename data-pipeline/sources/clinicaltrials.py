"""ClinicalTrials.gov API v2 — clinical pipeline (SPEC §5.2).

Shaped like `sources.edgar`: throttled, retrying, disk-cached, and returning raw
payloads for `transform.clinical` to interpret.

Three properties of the API decide how this module queries.

**Sponsors are matched whole-field, never by free text.** `query.spons` matches
collaborators as well as lead sponsors, and matches on tokens, so a query on
`Pfizer` returns thousands of studies led by universities. Counting that way
would attribute a university's trial to Pfizer. Every count here comes from
`AREA[LeadSponsorName]COVERAGE[FullMatch]"<exact string>"`, using strings
verified by `scripts/enumerate_sponsors.py` and confirmed by hand into
`universe.yaml`. Discovery and measurement are different jobs and this module
only does the second.

**Interventional only.** SPEC §5.2: otherwise counts are inflated by
investigator-initiated observational work the company did not run.

**A zero-trial result is an error, not a fact.** ClinicalTrials.gov tokenises, so
a company can be invisible to a query on its own name — Moderna's lead sponsor is
`ModernaTX, Inc.` and a query on `Moderna` returns one unrelated study. At sixty
tickers nobody notices a company silently reporting nothing, so an empty result
for a company that has sponsor strings configured raises rather than returns.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

from sources.edgar import RateLimiter

__all__ = [
    "INTERVENTIONAL",
    "ClinicalTrialsClient",
    "ClinicalTrialsError",
    "EmptyPipelineError",
    "Study",
    "exact_sponsor_filter",
    "read_study",
]

log = logging.getLogger(__name__)

BASE = "https://clinicaltrials.gov/api/v2/studies"

#: The API caps a page at 1000.
PAGE_SIZE = 1000

#: ClinicalTrials.gov publishes no rate limit. Three a second is polite and keeps
#: a full universe refresh well under a minute.
DEFAULT_REQUESTS_PER_SECOND = 3.0

DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 4
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

INTERVENTIONAL = "AREA[StudyType]INTERVENTIONAL"

#: SPEC §5.2's field list, restricted so a refresh moves megabytes rather than
#: gigabytes. The full record averages 17 kB.
FIELDS = ",".join(
    (
        "NCTId",
        "BriefTitle",
        "Phase",
        "OverallStatus",
        "Condition",
        "InterventionName",
        "InterventionType",
        "EnrollmentCount",
        "StudyType",
        "StartDate",
        "PrimaryCompletionDate",
        "CompletionDate",
        "LeadSponsorName",
        "WhyStopped",
    )
)


class ClinicalTrialsError(Exception):
    """Base class for failures raised by this module."""


class EmptyPipelineError(ClinicalTrialsError):
    """A company with configured sponsor strings returned no trials.

    Almost always a sponsor string that no longer matches — a renamed entity, or
    a tokenisation gap of the kind that hides Moderna behind `ModernaTX`. Raised
    rather than returned so a silent zero cannot reach the site.
    """


def exact_sponsor_filter(name: str) -> str:
    """Whole-field lead-sponsor match, interventional only.

    `COVERAGE[FullMatch]` is what makes it exact. Without it the same query also
    returns sponsors whose names merely contain the tokens: for Moderna, 113
    studies instead of the 99 it actually leads.
    """
    escaped = name.replace('"', '\\"')
    return f'AREA[LeadSponsorName]COVERAGE[FullMatch]"{escaped}" AND {INTERVENTIONAL}'


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


def _parse_partial_date(value: object) -> dt.date | None:
    """ClinicalTrials.gov dates are `YYYY-MM-DD`, `YYYY-MM` or `YYYY`.

    A month-only date becomes the first of that month. That is a real loss of
    precision, but the alternative is discarding a third of the start dates,
    which would corrupt every trailing-twelve-month count.
    """
    if not isinstance(value, str) or not value:
        return None
    parts = value.split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 1
        day = int(parts[2]) if len(parts) > 2 else 1
        return dt.date(year, month, day)
    except (ValueError, IndexError):
        return None


@dataclass(frozen=True)
class Study:
    """One interventional study, flattened out of the nested response."""

    nct_id: str
    title: str | None
    lead_sponsor: str | None
    status: str | None
    phases: tuple[str, ...]
    conditions: tuple[str, ...]
    enrollment: int | None
    start: dt.date | None
    primary_completion: dt.date | None
    completion: dt.date | None
    why_stopped: str | None
    #: Precision actually present in the filing, so a `YYYY` start is not treated
    #: as though the company said 1 January.
    start_precision: str | None = None

    @property
    def url(self) -> str:
        return f"https://clinicaltrials.gov/study/{self.nct_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "nct_id": self.nct_id,
            "title": self.title,
            "lead_sponsor": self.lead_sponsor,
            "status": self.status,
            "phases": list(self.phases),
            "conditions": list(self.conditions),
            "enrollment": self.enrollment,
            "start_date": self.start.isoformat() if self.start else None,
            "start_precision": self.start_precision,
            "primary_completion_date": (
                self.primary_completion.isoformat() if self.primary_completion else None
            ),
            "completion_date": self.completion.isoformat() if self.completion else None,
            "why_stopped": self.why_stopped,
            "url": self.url,
        }


def _precision(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return {1: "year", 2: "month"}.get(len(value.split("-")), "day")


def read_study(payload: Mapping[str, Any]) -> Study | None:
    """Flatten one nested `protocolSection` into a `Study`."""
    section = payload.get("protocolSection")
    if not isinstance(section, Mapping):
        return None

    ident = section.get("identificationModule") or {}
    status = section.get("statusModule") or {}
    sponsors = section.get("sponsorCollaboratorsModule") or {}
    conditions = section.get("conditionsModule") or {}
    design = section.get("designModule") or {}

    nct_id = ident.get("nctId")
    if not isinstance(nct_id, str):
        return None

    enrollment = (design.get("enrollmentInfo") or {}).get("count")
    start_struct = status.get("startDateStruct") or {}

    return Study(
        nct_id=nct_id,
        title=ident.get("briefTitle"),
        lead_sponsor=(sponsors.get("leadSponsor") or {}).get("name"),
        status=status.get("overallStatus"),
        phases=tuple(design.get("phases") or ()),
        conditions=tuple(conditions.get("conditions") or ()),
        enrollment=enrollment if isinstance(enrollment, int) else None,
        start=_parse_partial_date(start_struct.get("date")),
        start_precision=_precision(start_struct.get("date")),
        primary_completion=_parse_partial_date(
            (status.get("primaryCompletionDateStruct") or {}).get("date")
        ),
        completion=_parse_partial_date((status.get("completionDateStruct") or {}).get("date")),
        why_stopped=status.get("whyStopped"),
    )


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


@dataclass
class ClinicalTrialsClient:
    """Throttled, retrying, disk-cached reader for the ClinicalTrials.gov v2 API."""

    cache_dir: Path | None = None
    user_agent: str = "healthcare-equity-screener"
    requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND
    max_retries: int = DEFAULT_MAX_RETRIES
    timeout: float = DEFAULT_TIMEOUT
    session: requests.Session | None = None
    sleep: Any = time.sleep
    _limiter: RateLimiter = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent, "Accept": "application/json"})
        self._limiter = RateLimiter(self.requests_per_second, sleep=self.sleep)
        if self.cache_dir is not None:
            self.cache_dir = Path(self.cache_dir)

    # -- public API ------------------------------------------------------- #

    def studies_for_sponsor(self, sponsor: str, *, refresh: bool = False) -> list[Study]:
        """Every interventional study this sponsor leads."""
        out: list[Study] = []
        for raw in self._paginate({"filter.advanced": exact_sponsor_filter(sponsor)}, refresh=refresh):
            study = read_study(raw)
            if study is not None:
                out.append(study)
        return out

    def studies_for_company(
        self,
        sponsors: Sequence[str],
        *,
        exclusions: Sequence[str] = (),
        ticker: str = "",
        refresh: bool = False,
    ) -> list[Study]:
        """Every study across a company's sponsor strings, deduplicated.

        Exclusions are enforced here as well as by the queries, because a query
        is a filter and this is an assertion. Merck & Co and Merck KGaA of
        Darmstadt are unrelated listed companies; attributing one's pipeline to
        the other is the most damaging error available in this module, and a
        second line of defence costs one set comparison.
        """
        excluded = set(exclusions)
        overlap = excluded & set(sponsors)
        if overlap:
            raise ClinicalTrialsError(
                f"{ticker or 'company'}: sponsor string(s) both included and excluded: "
                f"{', '.join(sorted(overlap))}"
            )

        seen: dict[str, Study] = {}
        for sponsor in sponsors:
            for study in self.studies_for_sponsor(sponsor, refresh=refresh):
                if study.lead_sponsor in excluded:
                    raise ClinicalTrialsError(
                        f"{ticker or 'company'}: query for {sponsor!r} returned a study led by "
                        f"{study.lead_sponsor!r}, which is on the exclusion list ({study.nct_id})"
                    )
                seen.setdefault(study.nct_id, study)

        if sponsors and not seen:
            raise EmptyPipelineError(
                f"{ticker or 'company'}: {len(sponsors)} sponsor string(s) configured but no "
                "interventional studies returned. A sponsor string has probably stopped matching; "
                "rerun scripts/enumerate_sponsors.py."
            )
        return sorted(seen.values(), key=lambda s: s.nct_id)

    # -- internals -------------------------------------------------------- #

    def _cache_path(self, params: Mapping[str, Any]) -> Path | None:
        if self.cache_dir is None:
            return None
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()[:20]
        return self.cache_dir / f"{key}.json"

    def _paginate(self, params: Mapping[str, Any], *, refresh: bool) -> Iterable[Mapping[str, Any]]:
        token: str | None = None
        while True:
            page = {**params, "pageSize": PAGE_SIZE, "fields": FIELDS}
            if token:
                page["pageToken"] = token
            payload = self._get(page, refresh=refresh)
            yield from payload.get("studies", [])
            token = payload.get("nextPageToken")
            if not token:
                return

    def _get(self, params: Mapping[str, Any], *, refresh: bool) -> dict[str, Any]:
        path = self._cache_path(params)
        if path is not None and not refresh and path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                log.warning("discarding unreadable cache entry %s", path)

        payload = self._request(params)

        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(payload), encoding="utf-8")
                tmp.replace(path)
            except OSError as exc:
                log.warning("could not write cache entry %s: %s", path, exc)
        return payload

    def _request(self, params: Mapping[str, Any]) -> dict[str, Any]:
        assert self.session is not None
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
                    if not isinstance(payload, dict):
                        raise ClinicalTrialsError("expected a JSON object from ClinicalTrials.gov")
                    return payload
                if response.status_code not in RETRY_STATUSES:
                    raise ClinicalTrialsError(
                        f"ClinicalTrials.gov returned {response.status_code}: {response.text[:200]}"
                    )
                last = ClinicalTrialsError(f"HTTP {response.status_code}")
            if attempt < self.max_retries:
                self.sleep(min(16.0, 0.5 * 2**attempt))

        raise ClinicalTrialsError(f"giving up after {self.max_retries + 1} attempts: {last}")
