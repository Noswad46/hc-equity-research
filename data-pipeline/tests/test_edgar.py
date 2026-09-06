"""Tests for universe loading and the EDGAR HTTP client.

No test here touches the network. The client takes an injected session, so the
throttling, retry, caching and per-company resilience behaviour is exercised
against a stub that records what was asked for.
"""

from __future__ import annotations

import json

import pytest
import requests

from sources.edgar import (
    SUBSECTORS,
    Company,
    EdgarClient,
    EdgarError,
    EdgarHTTPError,
    EdgarNotFound,
    RateLimiter,
    UniverseError,
    load_universe,
    normalise_cik,
)

UA = "Test Runner test@example.com"


# --------------------------------------------------------------------------- #
# CIK normalisation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value,expected",
    [
        (78003, "0000078003"),
        ("78003", "0000078003"),
        ("0000078003", "0000078003"),
        ("CIK0000078003", "0000078003"),
        ("cik78003", "0000078003"),
        (1682852, "0001682852"),
        ("1234567890", "1234567890"),
    ],
)
def test_normalise_cik_accepts_the_shapes_ciks_arrive_in(value, expected):
    """`company_tickers.json` gives integers; `universe.yaml` gives padded strings."""
    assert normalise_cik(value) == expected


@pytest.mark.parametrize("value", [None, "", "abc", 12345678901, "12345678901", True, 3.5])
def test_normalise_cik_rejects_nonsense(value):
    with pytest.raises(UniverseError):
        normalise_cik(value)


# --------------------------------------------------------------------------- #
# The real universe file
# --------------------------------------------------------------------------- #


def test_universe_loads(universe_path):
    companies = load_universe(universe_path)

    assert len(companies) == 10  # SPEC §11 M1
    assert all(isinstance(c, Company) for c in companies)


def test_universe_ciks_are_ten_digits(universe_path):
    """data.sec.gov 404s on an unpadded CIK."""
    for company in load_universe(universe_path):
        assert len(company.cik) == 10 and company.cik.isdigit()


def test_universe_subsectors_are_in_the_enum(universe_path):
    for company in load_universe(universe_path):
        assert company.subsector in SUBSECTORS


def test_universe_urls_are_well_formed(universe_path):
    company = next(c for c in load_universe(universe_path) if c.ticker == "PFE")

    assert company.cik == "0000078003"
    assert company.companyfacts_url == (
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000078003.json"
    )
    assert company.submissions_url == "https://data.sec.gov/submissions/CIK0000078003.json"


def test_universe_covers_the_fixture_companies(universe_path):
    """Every company the tests assert real figures for must be in coverage."""
    tickers = {c.ticker for c in load_universe(universe_path)}

    assert {"PFE", "MRK", "MRNA", "BDX"} <= tickers


# --------------------------------------------------------------------------- #
# Universe validation
# --------------------------------------------------------------------------- #


def write_universe(tmp_path, text):
    path = tmp_path / "universe.yaml"
    path.write_text(text, encoding="utf-8")
    return path


VALID = """
- ticker: AAA
  cik: "0000000123"
  name: Alpha Inc.
  subsector: medtech
"""


def test_minimal_entry_is_accepted(tmp_path):
    company = load_universe(write_universe(tmp_path, VALID))[0]

    assert company.ticker == "AAA"
    assert company.therapeutic_focus == ()
    assert company.notes == ""


def test_unknown_subsector_is_rejected(tmp_path):
    text = VALID.replace("medtech", "biotechnology")

    with pytest.raises(UniverseError, match="unknown subsector"):
        load_universe(write_universe(tmp_path, text))


def test_duplicate_ticker_is_rejected(tmp_path):
    with pytest.raises(UniverseError, match="duplicate ticker"):
        load_universe(write_universe(tmp_path, VALID + VALID.replace("0000000123", "0000000456")))


def test_duplicate_cik_is_rejected(tmp_path):
    """Two tickers on one CIK would double-count a filer in the screener."""
    with pytest.raises(UniverseError, match="claimed by both"):
        load_universe(write_universe(tmp_path, VALID + VALID.replace("AAA", "BBB")))


@pytest.mark.parametrize("field", ["ticker", "cik", "name", "subsector"])
def test_missing_required_field_is_rejected(tmp_path, field):
    import yaml

    entry = {"ticker": "AAA", "cik": "0000000123", "name": "Alpha Inc.", "subsector": "medtech"}
    del entry[field]

    with pytest.raises(UniverseError, match="missing required field"):
        load_universe(write_universe(tmp_path, yaml.safe_dump([entry])))


def test_scalar_where_a_list_belongs_is_rejected(tmp_path):
    text = VALID + "  ct_sponsor_names: Alpha\n"

    with pytest.raises(UniverseError, match="must be a list"):
        load_universe(write_universe(tmp_path, text))


def test_empty_and_malformed_files_are_rejected(tmp_path):
    with pytest.raises(UniverseError, match="empty"):
        load_universe(write_universe(tmp_path, ""))
    with pytest.raises(UniverseError, match="must contain a list"):
        load_universe(write_universe(tmp_path, "ticker: AAA\n"))
    with pytest.raises(UniverseError, match="not found"):
        load_universe(tmp_path / "absent.yaml")


def test_ticker_is_upper_cased_and_lists_are_trimmed(tmp_path):
    text = VALID + '  therapeutic_focus: ["  vaccines  ", ""]\n'
    company = load_universe(write_universe(tmp_path, text.replace("AAA", "aaa")))[0]

    assert company.ticker == "AAA"
    assert company.therapeutic_focus == ("vaccines",)


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #


def test_rate_limiter_spaces_requests():
    """SEC allows 10 requests/second; the default sits below it."""
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds):  # a real sleep advances the clock
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(4.0, clock=lambda: now[0], sleep=sleep)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert slept == [0.25, 0.25]
    assert now[0] == pytest.approx(0.5)


def test_rate_limiter_does_not_sleep_when_time_has_already_passed():
    now = [0.0]
    slept: list[float] = []
    limiter = RateLimiter(4.0, clock=lambda: now[0], sleep=slept.append)

    limiter.acquire()
    now[0] = 100.0
    limiter.acquire()

    assert slept == []


def test_rate_limiter_rejects_a_nonpositive_rate():
    with pytest.raises(ValueError):
        RateLimiter(0)


# --------------------------------------------------------------------------- #
# HTTP client
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON object could be decoded")
        return self._payload


class FakeSession:
    """Stands in for `requests.Session`, replaying a scripted list of responses."""

    def __init__(self, *responses):
        self.headers: dict[str, str] = {}
        self.responses = list(responses)
        self.calls: list[str] = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        item = self.responses.pop(0) if self.responses else FakeResponse(200, {})
        if isinstance(item, Exception):
            raise item
        return item


def make_client(*responses, **kwargs):
    kwargs.setdefault("user_agent", UA)
    kwargs.setdefault("sleep", lambda _: None)
    return EdgarClient(session=FakeSession(*responses), **kwargs)


def test_user_agent_is_required(monkeypatch):
    """SEC rejects requests that do not identify a contact."""
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    with pytest.raises(EdgarError, match="User-Agent"):
        EdgarClient(session=FakeSession())


def test_user_agent_must_look_like_a_name_and_email(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    with pytest.raises(EdgarError, match="does not look like"):
        EdgarClient(user_agent="scraper", session=FakeSession())


def test_user_agent_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", UA)
    client = EdgarClient(session=FakeSession(), sleep=lambda _: None)

    assert client.session.headers["User-Agent"] == UA


def test_companyfacts_pads_the_cik_in_the_url():
    client = make_client(FakeResponse(200, {"cik": 78003}))
    client.fetch_companyfacts(78003)

    assert client.session.calls == [
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000078003.json"
    ]


def test_404_raises_not_found():
    client = make_client(FakeResponse(404))

    with pytest.raises(EdgarNotFound):
        client.fetch_companyfacts("0000000001")


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_statuses_are_retried(status):
    client = make_client(FakeResponse(status), FakeResponse(status), FakeResponse(200, {"ok": True}))

    assert client.fetch_companyfacts(1) == {"ok": True}
    assert len(client.session.calls) == 3


def test_retries_give_up_eventually():
    client = make_client(*[FakeResponse(503)] * 5, max_retries=2)

    with pytest.raises(EdgarHTTPError, match="giving up"):
        client.fetch_companyfacts(1)
    assert len(client.session.calls) == 3


def test_retry_after_header_is_honoured():
    slept: list[float] = []
    client = EdgarClient(
        user_agent=UA,
        session=FakeSession(FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, {})),
        sleep=slept.append,
    )
    client.fetch_companyfacts(1)

    assert 7.0 in slept


def test_client_errors_are_not_retried():
    client = make_client(FakeResponse(403))

    with pytest.raises(EdgarHTTPError) as exc:
        client.fetch_companyfacts(1)
    assert exc.value.status == 403
    assert len(client.session.calls) == 1


def test_network_errors_are_retried():
    client = make_client(requests.ConnectionError("boom"), FakeResponse(200, {"ok": True}))

    assert client.fetch_companyfacts(1) == {"ok": True}


def test_non_json_response_raises():
    client = make_client(FakeResponse(200, payload=None, text="<html>maintenance</html>"))

    with pytest.raises(EdgarHTTPError, match="did not return JSON"):
        client.fetch_companyfacts(1)


def test_json_that_is_not_an_object_raises():
    client = make_client(FakeResponse(200, payload=[1, 2, 3]))

    with pytest.raises(EdgarHTTPError, match="expected a JSON object"):
        client.fetch_companyfacts(1)


# --------------------------------------------------------------------------- #
# Caching
# --------------------------------------------------------------------------- #


def test_response_is_cached_and_reused(tmp_path):
    client = make_client(FakeResponse(200, {"cik": 1}), cache_dir=tmp_path)

    assert client.fetch_companyfacts(1) == {"cik": 1}
    assert client.fetch_companyfacts(1) == {"cik": 1}
    assert len(client.session.calls) == 1
    assert (tmp_path / "companyfacts" / "CIK0000000001.json").is_file()


def test_refresh_bypasses_the_cache(tmp_path):
    client = make_client(FakeResponse(200, {"v": 1}), FakeResponse(200, {"v": 2}), cache_dir=tmp_path)

    client.fetch_companyfacts(1)

    assert client.fetch_companyfacts(1, refresh=True) == {"v": 2}
    assert client.fetch_companyfacts(1) == {"v": 2}  # refreshed value was written back


def test_corrupt_cache_entry_is_refetched(tmp_path):
    path = tmp_path / "companyfacts" / "CIK0000000001.json"
    path.parent.mkdir(parents=True)
    path.write_text("{ truncated", encoding="utf-8")
    client = make_client(FakeResponse(200, {"ok": True}), cache_dir=tmp_path)

    assert client.fetch_companyfacts(1) == {"ok": True}
    assert json.loads(path.read_text()) == {"ok": True}


def test_no_temp_file_is_left_behind(tmp_path):
    client = make_client(FakeResponse(200, {"ok": True}), cache_dir=tmp_path)
    client.fetch_companyfacts(1)

    assert list((tmp_path / "companyfacts").glob("*.tmp")) == []


# --------------------------------------------------------------------------- #
# Per-company resilience (SPEC §10)
# --------------------------------------------------------------------------- #


def test_one_failure_does_not_stop_the_run():
    companies = [
        Company(ticker="AAA", cik="0000000001", name="A", subsector="medtech"),
        Company(ticker="BBB", cik="0000000002", name="B", subsector="medtech"),
        Company(ticker="CCC", cik="0000000003", name="C", subsector="medtech"),
    ]
    client = make_client(
        FakeResponse(200, {"cik": 1}),
        FakeResponse(404),
        FakeResponse(200, {"cik": 3}),
    )

    results = list(client.iter_companyfacts(companies))

    assert [c.ticker for c, _, _ in results] == ["AAA", "BBB", "CCC"]
    assert [f is not None for _, f, _ in results] == [True, False, True]
    assert isinstance(results[1][2], EdgarNotFound)


def test_network_failure_is_reported_not_raised():
    companies = [Company(ticker="AAA", cik="0000000001", name="A", subsector="medtech")]
    client = make_client(*[requests.ConnectionError("down")] * 6)

    (_, facts, error) = next(iter(client.iter_companyfacts(companies)))

    assert facts is None
    assert error is not None


# --------------------------------------------------------------------------- #
# Ticker map
# --------------------------------------------------------------------------- #


def test_company_tickers_map_is_normalised():
    payload = {
        "0": {"cik_str": 78003, "ticker": "PFE", "title": "PFIZER INC"},
        "1": {"cik_str": 1682852, "ticker": "mrna", "title": "Moderna, Inc."},
    }
    client = make_client(FakeResponse(200, payload))

    assert client.fetch_company_tickers() == {"PFE": "0000078003", "MRNA": "0001682852"}
