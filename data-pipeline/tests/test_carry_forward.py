"""Carrying a failed company forward, and knowing when to stop (SPEC §10).

SPEC §10 says a failure on one company must not fail the run and must not drop
that company from the site. Both halves matter, and the second one has a limit:
a row carried forever is not resilience, it is a site quietly serving month-old
figures under a current as-of date. These tests pin the bound.
"""

from __future__ import annotations

import json

from run import MAX_STALE_RUNS, _aged, _mark_stale, _previous_state

LAST_GOOD = "2026-09-01T00:00:00Z"


def row(ticker: str = "ABC", **extra) -> dict:
    return {"ticker": ticker, "revenue_ttm": 1_234, "stale": None, **extra}


def stale_row(consecutive: int, *, last_success_at: str = LAST_GOOD) -> dict:
    return row(
        stale={
            "last_success_at": last_success_at,
            "consecutive_failures": consecutive,
            "limit": MAX_STALE_RUNS,
            "error": "HTTP 503",
        }
    )


# --------------------------------------------------------------------------- #
# Ageing a row
# --------------------------------------------------------------------------- #


def test_first_failure_carries_the_row_and_dates_it():
    aged = _aged(row(), reason="HTTP 503", last_good=LAST_GOOD)

    assert aged is not None
    assert aged["revenue_ttm"] == 1_234, "figures must survive untouched"
    assert aged["stale"]["consecutive_failures"] == 1
    assert aged["stale"]["last_success_at"] == LAST_GOOD
    assert aged["stale"]["error"] == "HTTP 503"


def test_later_failures_keep_naming_the_last_good_run():
    """The date must not creep forward a week at a time.

    If it did, a row four weeks stale would claim to be one week old, which is
    the misreading the marker exists to prevent.
    """
    aged = _aged(stale_row(1), reason="HTTP 503", last_good="2026-09-08T00:00:00Z")

    assert aged["stale"]["consecutive_failures"] == 2
    assert aged["stale"]["last_success_at"] == LAST_GOOD


def test_a_row_is_carried_up_to_the_limit():
    aged = _aged(stale_row(MAX_STALE_RUNS - 1), reason="HTTP 503", last_good=LAST_GOOD)

    assert aged is not None
    assert aged["stale"]["consecutive_failures"] == MAX_STALE_RUNS


def test_a_row_past_the_limit_is_dropped_rather_than_carried():
    """Four weeks of failing is not stale, it is broken."""
    assert _aged(stale_row(MAX_STALE_RUNS), reason="HTTP 503", last_good=LAST_GOOD) is None


def test_the_original_row_is_not_mutated():
    original = stale_row(1)
    _aged(original, reason="HTTP 503", last_good=LAST_GOOD)

    assert original["stale"]["consecutive_failures"] == 1


def test_a_successful_refresh_clears_the_marker():
    """Recovery is just a fresh row overwriting the carried one.

    `company_document` emits `stale: None`, so nothing has to remember to reset
    a counter — the row that replaces the stale one has no marker on it.
    """
    aged = _aged(stale_row(3), reason="HTTP 503", last_good=LAST_GOOD)
    assert aged["stale"]["consecutive_failures"] == 4

    fresh = row()
    assert fresh["stale"] is None
    assert _aged(fresh, reason="HTTP 503", last_good=LAST_GOOD)["stale"]["consecutive_failures"] == 1


# --------------------------------------------------------------------------- #
# Reading the previous state
# --------------------------------------------------------------------------- #


def test_no_previous_file_means_nothing_to_carry(tmp_path):
    assert _previous_state(tmp_path) == ({}, None)


def test_unreadable_previous_file_is_not_an_error(tmp_path):
    """A corrupt file must not take the run down with it."""
    (tmp_path / "screener.json").write_text("{not json", encoding="utf-8")

    assert _previous_state(tmp_path) == ({}, None)


def test_previous_rows_are_keyed_by_ticker(tmp_path):
    (tmp_path / "screener.json").write_text(
        json.dumps({"generated_at": LAST_GOOD, "companies": [row("ABC"), row("XYZ")]}),
        encoding="utf-8",
    )

    rows, generated_at = _previous_state(tmp_path)

    assert sorted(rows) == ["ABC", "XYZ"]
    assert generated_at == LAST_GOOD


# --------------------------------------------------------------------------- #
# Marking the company document
# --------------------------------------------------------------------------- #


def test_marking_leaves_every_figure_alone(tmp_path):
    path = tmp_path / "ABC.json"
    before = {"ticker": "ABC", "revenue_ttm": 1_234, "quarterly": [{"revenue": 99}], "stale": None}
    path.write_text(json.dumps(before), encoding="utf-8")

    assert _mark_stale(path, {"consecutive_failures": 2, "last_success_at": LAST_GOOD})

    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["stale"]["consecutive_failures"] == 2
    assert {k: v for k, v in after.items() if k != "stale"} == {
        k: v for k, v in before.items() if k != "stale"
    }


def test_marking_a_missing_document_reports_failure(tmp_path):
    """The caller drops the row instead: a row with no page behind it is worse
    than no row."""
    assert _mark_stale(tmp_path / "GONE.json", {"consecutive_failures": 1}) is False


def test_marking_an_unreadable_document_reports_failure(tmp_path):
    path = tmp_path / "ABC.json"
    path.write_text("{not json", encoding="utf-8")

    assert _mark_stale(path, {"consecutive_failures": 1}) is False
