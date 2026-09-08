"""SEC EDGAR XBRL company facts.

Implements the fetch half of SPEC §5.1: read the curated universe, then pull the
raw `companyfacts` payload for each CIK. Nothing in here interprets the facts —
tag resolution and period arithmetic live in `transform.fundamentals`.

Two SEC requirements are load-bearing and enforced here rather than left to the
caller: the CIK must be zero-padded to ten digits, and every request must carry a
`User-Agent` naming a real person and email address. Requests without one are
rejected outright.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

import requests
import yaml

__all__ = [
    "SUBSECTORS",
    "Company",
    "EdgarClient",
    "EdgarError",
    "EdgarHTTPError",
    "EdgarNotFound",
    "RateLimiter",
    "UniverseError",
    "load_universe",
    "normalise_cik",
]

log = logging.getLogger(__name__)

BASE_DATA = "https://data.sec.gov"
BASE_WWW = "https://www.sec.gov"

COMPANY_TICKERS_URL = f"{BASE_WWW}/files/company_tickers.json"
COMPANYFACTS_URL = BASE_DATA + "/api/xbrl/companyfacts/CIK{cik}.json"
COMPANYCONCEPT_URL = BASE_DATA + "/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{tag}.json"
SUBMISSIONS_URL = BASE_DATA + "/submissions/CIK{cik}.json"

#: SEC publishes a 10 requests/second ceiling. Default below it, since the limit
#: is enforced per source IP and CI runners are shared.
DEFAULT_REQUESTS_PER_SECOND = 8.0

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 4
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

USER_AGENT_ENV = "SEC_USER_AGENT"

#: SPEC §4.
SUBSECTORS = frozenset(
    {
        "large_cap_pharma",
        "commercial_biotech",
        "clinical_stage_biotech",
        "vaccines_infectious_disease",
        "medtech",
        "diagnostics",
        "life_science_tools",
        "payer",
        "provider",
        "hcit",
        "distributor",
    }
)


class EdgarError(Exception):
    """Base class for every failure raised by this module."""


class EdgarHTTPError(EdgarError):
    """A request failed, or kept failing across retries."""

    def __init__(self, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class EdgarNotFound(EdgarHTTPError):
    """EDGAR has no document at this URL.

    Raised for 404s, which for `companyfacts` means the filer has never submitted
    XBRL facts. That is a per-company data gap, not a pipeline failure — SPEC §10
    requires the run to continue.
    """


class UniverseError(EdgarError):
    """`universe.yaml` is malformed."""


# --------------------------------------------------------------------------- #
# Universe
# --------------------------------------------------------------------------- #

_CIK_DIGITS = re.compile(r"(\d+)")


def normalise_cik(value: object) -> str:
    """Return `value` as a zero-padded 10-digit CIK string.

    Accepts the several shapes a CIK arrives in — ``78003``, ``"78003"``,
    ``"0000078003"``, ``"CIK0000078003"`` — because `company_tickers.json` gives
    integers while `universe.yaml` gives strings.
    """
    if isinstance(value, bool):  # bool is an int subclass; never a valid CIK
        raise UniverseError(f"invalid CIK: {value!r}")
    if isinstance(value, int):
        digits = str(value)
    elif isinstance(value, str):
        match = _CIK_DIGITS.search(value)
        if match is None:
            raise UniverseError(f"invalid CIK: {value!r}")
        digits = match.group(1)
    else:
        raise UniverseError(f"invalid CIK: {value!r}")

    digits = digits.lstrip("0") or "0"
    if len(digits) > 10:
        raise UniverseError(f"CIK has more than 10 significant digits: {value!r}")
    return digits.zfill(10)


@dataclass(frozen=True)
class Company:
    """One row of `universe.yaml` (SPEC §4)."""

    ticker: str
    cik: str
    name: str
    subsector: str
    therapeutic_focus: tuple[str, ...] = ()
    ct_sponsor_names: tuple[str, ...] = ()
    #: Lead-sponsor strings that must never enter this company's record, even if
    #: a future query surfaces them. Merck KGaA of Darmstadt is a different
    #: listed company sharing a name; Organon and Upjohn/Viatris are divested
    #: businesses whose trials left with the divestiture.
    ct_sponsor_exclusions: tuple[str, ...] = ()
    fda_applicant_names: tuple[str, ...] = ()
    index_membership: tuple[str, ...] = ()
    notes: str = ""

    @property
    def companyfacts_url(self) -> str:
        return COMPANYFACTS_URL.format(cik=self.cik)

    @property
    def submissions_url(self) -> str:
        return SUBMISSIONS_URL.format(cik=self.cik)

    @property
    def filings_url(self) -> str:
        """Human-readable EDGAR landing page, for the Sources section of SPEC §8."""
        return f"{BASE_WWW}/cgi-bin/browse-edgar?action=getcompany&CIK={self.cik}&type=10-&dateb=&owner=include&count=40"


_REQUIRED_FIELDS = ("ticker", "cik", "name", "subsector")
_LIST_FIELDS = (
    "therapeutic_focus",
    "ct_sponsor_names",
    "ct_sponsor_exclusions",
    "fda_applicant_names",
    "index_membership",
)


def _as_str_tuple(value: object, *, ticker: str, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise UniverseError(f"{ticker}: {field_name} must be a list, got {value!r}")
    out = []
    for item in value:
        if not isinstance(item, str):
            raise UniverseError(f"{ticker}: {field_name} entries must be strings, got {item!r}")
        item = item.strip()
        if item:
            out.append(item)
    return tuple(out)


def load_universe(path: str | os.PathLike[str]) -> list[Company]:
    """Parse and validate `universe.yaml`.

    Validation is strict on purpose. A typo in a subsector or a duplicated CIK
    would otherwise surface much later as a silently missing table row.
    """
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UniverseError(f"universe file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise UniverseError(f"{path} is not valid YAML: {exc}") from exc

    if raw is None:
        raise UniverseError(f"{path} is empty")
    if not isinstance(raw, list):
        raise UniverseError(f"{path} must contain a list of companies, got {type(raw).__name__}")

    companies: list[Company] = []
    seen_tickers: dict[str, int] = {}
    seen_ciks: dict[str, str] = {}

    for index, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            raise UniverseError(f"{path} entry {index} must be a mapping, got {type(entry).__name__}")

        missing = [f for f in _REQUIRED_FIELDS if not entry.get(f)]
        if missing:
            raise UniverseError(f"{path} entry {index} is missing required field(s): {', '.join(missing)}")

        ticker = str(entry["ticker"]).strip().upper()
        if ticker in seen_tickers:
            raise UniverseError(f"duplicate ticker {ticker} (entries {seen_tickers[ticker]} and {index})")
        seen_tickers[ticker] = index

        cik = normalise_cik(entry["cik"])
        if cik in seen_ciks:
            raise UniverseError(f"CIK {cik} is claimed by both {seen_ciks[cik]} and {ticker}")
        seen_ciks[cik] = ticker

        subsector = str(entry["subsector"]).strip()
        if subsector not in SUBSECTORS:
            raise UniverseError(
                f"{ticker}: unknown subsector {subsector!r}; expected one of {', '.join(sorted(SUBSECTORS))}"
            )

        lists = {f: _as_str_tuple(entry.get(f), ticker=ticker, field_name=f) for f in _LIST_FIELDS}

        contradiction = set(lists["ct_sponsor_names"]) & set(lists["ct_sponsor_exclusions"])
        if contradiction:
            raise UniverseError(
                f"{ticker}: sponsor string(s) both included and excluded: "
                f"{', '.join(sorted(contradiction))}"
            )

        companies.append(
            Company(
                ticker=ticker,
                cik=cik,
                name=str(entry["name"]).strip(),
                subsector=subsector,
                notes=str(entry.get("notes") or "").strip(),
                **lists,
            )
        )

    if not companies:
        raise UniverseError(f"{path} contains no companies")
    return companies


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


class RateLimiter:
    """Blocking minimum-interval throttle, shared across threads."""

    def __init__(
        self,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.min_interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_allowed = float("-inf")

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next_allowed - now
            if wait > 0:
                self._sleep(wait)
                now = self._next_allowed
            self._next_allowed = now + self.min_interval


def _validate_user_agent(user_agent: str | None) -> str:
    """SEC rejects requests whose User-Agent does not identify a real contact."""
    candidate = (user_agent or os.environ.get(USER_AGENT_ENV) or "").strip()
    if not candidate:
        raise EdgarError(
            "SEC requires a User-Agent identifying a real name and email address. "
            f"Pass user_agent= or set {USER_AGENT_ENV}, e.g. 'Jane Doe jane@example.com'."
        )
    if "@" not in candidate or " " not in candidate:
        raise EdgarError(
            f"User-Agent {candidate!r} does not look like 'Name email@example.com'; "
            "SEC rejects requests that do not identify a contact."
        )
    return candidate


@dataclass
class EdgarClient:
    """Throttled, retrying, disk-cached reader for the EDGAR JSON APIs.

    `cache_dir` holds raw responses exactly as EDGAR returned them (SPEC §3 keeps
    this gitignored). A cached file is used unconditionally unless `refresh=True`;
    the pipeline runs weekly against data that moves quarterly, so staleness is
    cheap and re-fetching 60 multi-megabyte payloads is not.
    """

    user_agent: str | None = None
    cache_dir: Path | None = None
    requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND
    max_retries: int = DEFAULT_MAX_RETRIES
    timeout: float = DEFAULT_TIMEOUT
    session: requests.Session | None = None
    sleep: Callable[[float], None] = time.sleep
    _limiter: RateLimiter = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.user_agent = _validate_user_agent(self.user_agent)
        if self.cache_dir is not None:
            self.cache_dir = Path(self.cache_dir)
        if self.session is None:
            self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self._limiter = RateLimiter(self.requests_per_second, sleep=self.sleep)

    # -- public API ------------------------------------------------------- #

    def fetch_companyfacts(self, cik: object, *, refresh: bool = False) -> dict[str, Any]:
        """Every XBRL fact EDGAR holds for one filer."""
        cik = normalise_cik(cik)
        return self._get_json(
            COMPANYFACTS_URL.format(cik=cik),
            cache_key=f"companyfacts/CIK{cik}.json",
            refresh=refresh,
        )

    def fetch_companyconcept(
        self, cik: object, tag: str, *, taxonomy: str = "us-gaap", refresh: bool = False
    ) -> dict[str, Any]:
        """One concept's time series. Not used by M1; `companyfacts` covers it in one request."""
        cik = normalise_cik(cik)
        return self._get_json(
            COMPANYCONCEPT_URL.format(cik=cik, taxonomy=taxonomy, tag=tag),
            cache_key=f"companyconcept/CIK{cik}-{taxonomy}-{tag}.json",
            refresh=refresh,
        )

    def fetch_submissions(self, cik: object, *, refresh: bool = False) -> dict[str, Any]:
        """Filing history and shares outstanding."""
        cik = normalise_cik(cik)
        return self._get_json(
            SUBMISSIONS_URL.format(cik=cik),
            cache_key=f"submissions/CIK{cik}.json",
            refresh=refresh,
        )

    def fetch_company_tickers(self, *, refresh: bool = False) -> dict[str, str]:
        """Ticker -> zero-padded CIK, for checking `universe.yaml` against EDGAR."""
        payload = self._get_json(
            COMPANY_TICKERS_URL, cache_key="company_tickers.json", refresh=refresh
        )
        return {
            str(row["ticker"]).upper(): normalise_cik(row["cik_str"])
            for row in payload.values()
            if isinstance(row, Mapping) and row.get("ticker")
        }

    def iter_companyfacts(
        self, companies: Sequence[Company], *, refresh: bool = False
    ) -> Iterator[tuple[Company, dict[str, Any] | None, Exception | None]]:
        """Yield `(company, facts, error)` for each company, never raising.

        SPEC §10: one company failing must not fail the run. Callers record the
        error in `meta.json` and keep the previous good record for that ticker.
        """
        for company in companies:
            try:
                yield company, self.fetch_companyfacts(company.cik, refresh=refresh), None
            except EdgarError as exc:
                log.warning("EDGAR fetch failed for %s (CIK %s): %s", company.ticker, company.cik, exc)
                yield company, None, exc
            except requests.RequestException as exc:  # network died mid-run
                log.warning("EDGAR request error for %s (CIK %s): %s", company.ticker, company.cik, exc)
                yield company, None, exc

    # -- internals -------------------------------------------------------- #

    def _cache_path(self, cache_key: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / cache_key

    def _get_json(self, url: str, *, cache_key: str, refresh: bool) -> dict[str, Any]:
        path = self._cache_path(cache_key)
        if path is not None and not refresh and path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                log.warning("discarding unreadable cache entry %s", path)

        payload = self._request_json(url)

        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(json.dumps(payload), encoding="utf-8")
                tmp.replace(path)  # atomic, so an interrupted run leaves no half file
            except OSError as exc:
                log.warning("could not write cache entry %s: %s", path, exc)

        return payload

    def _request_json(self, url: str) -> dict[str, Any]:
        assert self.session is not None
        last: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self._limiter.acquire()
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last = exc
                if attempt == self.max_retries:
                    break
                self.sleep(self._backoff(attempt))
                continue

            status = response.status_code
            if status == 404:
                raise EdgarNotFound(f"no EDGAR document at {url}", url=url, status=404)
            if status in RETRY_STATUSES:
                last = EdgarHTTPError(f"HTTP {status} from {url}", url=url, status=status)
                if attempt == self.max_retries:
                    break
                self.sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if status >= 400:
                raise EdgarHTTPError(f"HTTP {status} from {url}", url=url, status=status)

            try:
                payload = response.json()
            except ValueError as exc:
                raise EdgarHTTPError(f"{url} did not return JSON: {exc}", url=url, status=status) from exc
            if not isinstance(payload, dict):
                raise EdgarHTTPError(
                    f"{url} returned {type(payload).__name__}, expected a JSON object", url=url, status=status
                )
            return payload

        raise EdgarHTTPError(
            f"giving up on {url} after {self.max_retries + 1} attempts: {last}",
            url=url,
            status=getattr(last, "status", None),
        )

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None = None) -> float:
        if retry_after:
            try:
                return max(0.0, min(60.0, float(retry_after)))
            except ValueError:
                pass
        return min(16.0, 0.5 * (2**attempt))


def _main(argv: Sequence[str] | None = None) -> int:
    """Fetch companyfacts for the whole universe into the cache."""
    import argparse

    here = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--universe", type=Path, default=here / "universe.yaml")
    parser.add_argument("--cache-dir", type=Path, default=here / "cache")
    parser.add_argument("--user-agent", default=None, help=f"defaults to ${USER_AGENT_ENV}")
    parser.add_argument("--refresh", action="store_true", help="ignore cached responses")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    companies = load_universe(args.universe)
    client = EdgarClient(user_agent=args.user_agent, cache_dir=args.cache_dir)

    failed = 0
    for company, facts, error in client.iter_companyfacts(companies):
        if error is not None:
            failed += 1
            print(f"{company.ticker:6} FAILED  {error}")
            continue
        taxonomies = ", ".join(sorted(facts.get("facts", {}))) or "none"
        print(f"{company.ticker:6} ok      {facts.get('entityName', '?')}  [{taxonomies}]")

    print(f"\n{len(companies) - failed}/{len(companies)} companies fetched")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
