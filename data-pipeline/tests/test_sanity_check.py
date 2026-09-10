"""The gate between a bad refresh and the live site.

The workflow commits to `main` and Cloudflare deploys it, so these checks are
the last thing standing between a broken run and a published page. What matters
here is that each one actually fires — a gate that passes everything is worse
than no gate, because it reads as assurance.
"""

from __future__ import annotations

import datetime as dt
import json

from scripts.sanity_check import (
    MAX_NULL_REVENUE_SHARE,
    MAX_ROW_DROP,
    check_failures,
    check_freshness,
    check_null_revenue,
    check_row_count,
    check_size,
    main,
    run_checks,
)

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


def rows(n: int, *, without_revenue: int = 0) -> list[dict]:
    return [
        {"ticker": f"T{i}", "revenue_ttm": None if i < without_revenue else 1_000}
        for i in range(n)
    ]


def meta(failed: int = 0, *, universe: int = 58, dropped: int = 0, share: float = 0.1) -> dict:
    return {
        "universe_size": universe,
        "sources": {
            "edgar": {
                "companies_failed": [{"ticker": f"F{i}"} for i in range(failed)],
                "companies_dropped": [{"ticker": f"D{i}"} for i in range(dropped)],
            }
        },
        "thresholds": {"alert_failure_share": share},
    }


# --------------------------------------------------------------------------- #
# Row count
# --------------------------------------------------------------------------- #


def test_a_steady_universe_passes():
    assert check_row_count(rows(58), rows(58)).ok


def test_losing_a_few_rows_passes():
    """Carried-forward rows mean an ordinary bad fetch costs no rows at all, so
    a small drop is a deliberate universe edit rather than a fault."""
    assert check_row_count(rows(58 - MAX_ROW_DROP), rows(58)).ok


def test_losing_more_than_the_limit_fails():
    finding = check_row_count(rows(58 - MAX_ROW_DROP - 1), rows(58))
    assert not finding.ok
    assert "down 4" in finding.detail


def test_an_empty_screener_fails_even_with_no_baseline():
    assert not check_row_count([], None).ok


def test_a_first_run_has_nothing_to_compare_and_passes():
    finding = check_row_count(rows(58), None)
    assert finding.ok
    assert "no committed baseline" in finding.detail


def test_growing_the_universe_is_never_a_failure():
    assert check_row_count(rows(120), rows(58)).ok


# --------------------------------------------------------------------------- #
# File size
# --------------------------------------------------------------------------- #


def test_a_normal_size_drift_passes():
    assert check_size(210_000, 209_879).ok


def test_a_collapsed_file_fails():
    finding = check_size(40_000, 209_879)
    assert not finding.ok
    assert "0.19x" in finding.detail


def test_a_ballooned_file_fails():
    assert not check_size(900_000, 209_879).ok


def test_an_empty_file_fails():
    assert not check_size(0, 209_879).ok


# --------------------------------------------------------------------------- #
# Revenue coverage
# --------------------------------------------------------------------------- #


def test_genuinely_pre_revenue_companies_do_not_trip_the_check():
    """Three of fifty-eight is the real figure, not a fault."""
    assert check_null_revenue(rows(58, without_revenue=3)).ok


def test_revenue_resolution_breaking_fails():
    finding = check_null_revenue(rows(58, without_revenue=20))
    assert not finding.ok
    assert f"{MAX_NULL_REVENUE_SHARE:.0%}" in finding.detail


def test_the_failing_tickers_are_named():
    finding = check_null_revenue(rows(58, without_revenue=20))
    assert "T0" in finding.detail


# --------------------------------------------------------------------------- #
# Fetch failures
# --------------------------------------------------------------------------- #


def test_a_clean_run_passes():
    assert check_failures(meta(failed=0)).ok


def test_a_few_failures_are_expected_and_pass():
    """SPEC §10's whole point: some companies failing is normal operation."""
    assert check_failures(meta(failed=3)).ok


def test_a_widespread_outage_fails():
    finding = check_failures(meta(failed=30))
    assert not finding.ok
    assert "alert threshold" in finding.detail


def test_the_threshold_comes_from_meta():
    assert check_failures(meta(failed=20, share=0.5)).ok
    assert not check_failures(meta(failed=20, share=0.01)).ok


def test_meta_without_a_universe_size_fails():
    assert not check_failures({"sources": {}}).ok


# --------------------------------------------------------------------------- #
# Freshness — the guard against committing a crashed run's leftovers
# --------------------------------------------------------------------------- #


def test_output_written_by_this_run_passes():
    finding = check_freshness(
        {"generated_at": "2026-09-10T11:30:00Z"}, now=NOW, max_age_hours=6
    )
    assert finding.ok


def test_output_left_over_from_an_earlier_run_fails():
    """`run.py` writes meta.json last, so an old stamp means it never got there
    — while some company files may already have been rewritten."""
    finding = check_freshness(
        {"generated_at": "2026-09-03T11:30:00Z"}, now=NOW, max_age_hours=6
    )
    assert not finding.ok
    assert "did not write it" in finding.detail


def test_a_missing_or_broken_timestamp_fails():
    assert not check_freshness({}, now=NOW, max_age_hours=6).ok
    assert not check_freshness({"generated_at": "last tuesday"}, now=NOW, max_age_hours=6).ok


def test_freshness_is_off_unless_asked_for():
    """Running the gate over a committed dataset a day later must not fail it."""
    names = [
        f.name
        for f in run_checks(
            screener={"companies": rows(58, without_revenue=3)},
            meta=meta(),
            size=209_879,
            baseline_screener=None,
            baseline_size=None,
        )
    ]
    assert "freshness" not in names


# --------------------------------------------------------------------------- #
# Together
# --------------------------------------------------------------------------- #


def test_a_healthy_run_passes_every_check():
    findings = run_checks(
        screener={"companies": rows(58, without_revenue=3)},
        meta=meta(failed=1),
        size=209_879,
        baseline_screener={"companies": rows(58)},
        baseline_size=209_000,
    )
    assert all(f.ok for f in findings), [f.detail for f in findings if not f.ok]


def test_a_catastrophic_run_is_caught_by_every_check():
    """Half the universe gone, the file with it, revenue unresolved, EDGAR down."""
    findings = run_checks(
        screener={"companies": rows(28, without_revenue=20)},
        meta=meta(failed=30),
        size=60_000,
        baseline_screener={"companies": rows(58)},
        baseline_size=209_879,
    )
    assert [f.name for f in findings if not f.ok] == [
        "row count",
        "file size",
        "revenue coverage",
        "fetch failures",
    ]


# --------------------------------------------------------------------------- #
# The exit code, which is the only part the workflow reads
# --------------------------------------------------------------------------- #


def write_data(tmp_path, screener: dict, meta_doc: dict):
    (tmp_path / "screener.json").write_text(json.dumps(screener), encoding="utf-8")
    (tmp_path / "meta.json").write_text(json.dumps(meta_doc), encoding="utf-8")
    return ["--data-dir", str(tmp_path)]


def test_main_exits_zero_on_a_healthy_run(tmp_path):
    argv = write_data(tmp_path, {"companies": rows(58, without_revenue=3)}, meta(failed=1))
    assert main(argv) == 0


def test_main_exits_non_zero_on_a_bad_run(tmp_path):
    argv = write_data(tmp_path, {"companies": rows(58, without_revenue=40)}, meta(failed=1))
    assert main(argv) == 1


def test_main_exits_non_zero_when_the_run_wrote_nothing(tmp_path):
    assert main(["--data-dir", str(tmp_path)]) == 1


def test_main_exits_non_zero_on_unparseable_output(tmp_path):
    (tmp_path / "screener.json").write_text("{truncated", encoding="utf-8")
    (tmp_path / "meta.json").write_text("{}", encoding="utf-8")
    assert main(["--data-dir", str(tmp_path)]) == 1


def test_a_data_dir_outside_the_repo_does_not_crash_the_gate(tmp_path):
    """There is no committed version of an untracked path; that is not a fault."""
    argv = write_data(tmp_path, {"companies": rows(58, without_revenue=3)}, meta())
    assert main(argv) == 0
