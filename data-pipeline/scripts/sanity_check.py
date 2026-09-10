"""Cheap assertions that stand between a bad pipeline run and the live site.

The refresh workflow commits straight to `main`, and Cloudflare Pages deploys
whatever lands there. Nothing else sits in that path, so this does: it compares
what the run just wrote against what is currently committed, and exits non-zero
if the new files look wrong in a way a human should see first.

These are guards against shipping garbage, not against failing. A run where some
companies failed is expected and fine — SPEC §10 says so, and those companies
are carried forward or dropped by `run.py` rather than silently vanishing. What
this catches is the shape of the dataset changing in a way no ordinary refresh
would explain: half the universe gone, the file collapsing, revenue stopping
resolving. Every check is deliberately blunt, because a subtle check that needs
tuning is a check that will be wrong at 3am.

Exit code 0 means commit. Non-zero means stop and look.

    python scripts/sanity_check.py                       # against HEAD
    python scripts/sanity_check.py --baseline-ref origin/main
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "src" / "data"

#: How many rows the universe may lose in one refresh before it needs a human.
#: `run.py` carries a failed company forward rather than dropping it, so a real
#: drop means either a deliberate universe edit or a company that has been
#: failing for a month — both worth seeing before they reach the site.
MAX_ROW_DROP = 3

#: Bounds on how much `screener.json` may change size in one refresh. Wide on
#: purpose: this catches a truncated write or a runaway duplication, not the
#: ordinary few-percent drift of a quarter's figures landing.
SIZE_RATIO_MIN = 0.5
SIZE_RATIO_MAX = 2.0

#: Share of rows allowed to carry no TTM revenue. The universe genuinely
#: contains pre-revenue biotechs — three of fifty-eight at the time of writing,
#: about 5% — so this is not zero. A jump past this is the signature of revenue
#: tag resolution breaking, which would otherwise ship as a page full of nulls.
MAX_NULL_REVENUE_SHARE = 0.15

#: Used when `meta.json` carries no threshold of its own.
DEFAULT_ALERT_FAILURE_SHARE = 0.1


@dataclass(frozen=True)
class Finding:
    ok: bool
    name: str
    detail: str


# --------------------------------------------------------------------------- #
# Checks. Pure functions over already-loaded data, so they can be tested
# without a git repository or a pipeline run behind them.
# --------------------------------------------------------------------------- #


def check_row_count(rows: Sequence[Any], baseline_rows: Sequence[Any] | None) -> Finding:
    n = len(rows)
    if n == 0:
        return Finding(False, "row count", "screener.json has no companies in it")
    if baseline_rows is None:
        return Finding(True, "row count", f"{n} rows (no committed baseline to compare)")

    lost = len(baseline_rows) - n
    if lost > MAX_ROW_DROP:
        return Finding(
            False,
            "row count",
            f"{n} rows, down {lost} from {len(baseline_rows)} — more than the {MAX_ROW_DROP} "
            "a single refresh should ever lose",
        )
    return Finding(True, "row count", f"{n} rows (was {len(baseline_rows)})")


def check_size(size: int, baseline_size: int | None) -> Finding:
    if size == 0:
        return Finding(False, "file size", "screener.json is empty")
    if not baseline_size:
        return Finding(True, "file size", f"{size} bytes (no committed baseline to compare)")

    ratio = size / baseline_size
    if not (SIZE_RATIO_MIN <= ratio <= SIZE_RATIO_MAX):
        return Finding(
            False,
            "file size",
            f"screener.json is {size} bytes against {baseline_size} committed "
            f"({ratio:.2f}x, outside {SIZE_RATIO_MIN}–{SIZE_RATIO_MAX}x)",
        )
    return Finding(True, "file size", f"{size} bytes ({ratio:.2f}x committed)")


def check_null_revenue(rows: Sequence[Mapping[str, Any]]) -> Finding:
    if not rows:
        return Finding(False, "revenue coverage", "no rows to check")

    missing = [r.get("ticker", "?") for r in rows if r.get("revenue_ttm") is None]
    share = len(missing) / len(rows)
    detail = f"{len(missing)}/{len(rows)} rows have no TTM revenue ({share:.1%})"
    if share > MAX_NULL_REVENUE_SHARE:
        shown = ", ".join(sorted(missing)[:10])
        return Finding(
            False,
            "revenue coverage",
            f"{detail}, over the {MAX_NULL_REVENUE_SHARE:.0%} ceiling — {shown}",
        )
    return Finding(True, "revenue coverage", detail)


def check_freshness(meta: Mapping[str, Any], *, now: dt.datetime, max_age_hours: float) -> Finding:
    """Confirm `meta.json` was written by the run that just finished.

    `run.py` writes `meta.json` and `screener.json` last, so a crash part-way
    leaves them untouched while some `companies/*.json` have already been
    rewritten. Committing that would publish a dataset whose company pages and
    screener disagree. An old timestamp here is the cheapest way to spot it.

    Off unless asked for, because "recent" is only meaningful inside the run —
    checking a committed dataset a day later should not fail for being a day old.
    """
    stamp = meta.get("generated_at")
    if not stamp:
        return Finding(False, "freshness", "meta.json carries no generated_at")
    try:
        written = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return Finding(False, "freshness", f"meta.json generated_at is unparseable: {stamp!r}")

    age_hours = (now - written).total_seconds() / 3600
    if age_hours > max_age_hours:
        return Finding(
            False,
            "freshness",
            f"meta.json is {age_hours:.1f}h old ({stamp}) — this run did not write it, "
            "so the output on disk is left over from an earlier one",
        )
    return Finding(True, "freshness", f"written {age_hours:.1f}h ago ({stamp})")


def check_failures(meta: Mapping[str, Any]) -> Finding:
    edgar = (meta.get("sources") or {}).get("edgar") or {}
    failed = edgar.get("companies_failed") or []
    dropped = edgar.get("companies_dropped") or []
    universe = meta.get("universe_size") or 0
    share_limit = (meta.get("thresholds") or {}).get(
        "alert_failure_share", DEFAULT_ALERT_FAILURE_SHARE
    )

    if not universe:
        return Finding(False, "fetch failures", "meta.json reports no universe size")

    share = len(failed) / universe
    detail = f"{len(failed)}/{universe} companies failed ({share:.1%}), {len(dropped)} dropped"
    if share > share_limit:
        return Finding(
            False, "fetch failures", f"{detail}, over the {share_limit:.0%} alert threshold"
        )
    return Finding(True, "fetch failures", detail)


def run_checks(
    *,
    screener: Mapping[str, Any],
    meta: Mapping[str, Any],
    size: int,
    baseline_screener: Mapping[str, Any] | None,
    baseline_size: int | None,
    now: dt.datetime | None = None,
    max_age_hours: float | None = None,
) -> list[Finding]:
    rows = screener.get("companies") or []
    baseline_rows = None if baseline_screener is None else (baseline_screener.get("companies") or [])
    findings = [
        check_row_count(rows, baseline_rows),
        check_size(size, baseline_size),
        check_null_revenue(rows),
        check_failures(meta),
    ]
    if max_age_hours is not None:
        findings.append(
            check_freshness(
                meta, now=now or dt.datetime.now(dt.timezone.utc), max_age_hours=max_age_hours
            )
        )
    return findings


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def committed_blob(ref: str, path: str) -> bytes | None:
    """The committed bytes of a file, or None when there is no such version.

    A first run, a new file or a shallow checkout that cannot see the ref all
    land here. None means "nothing to compare against", not "comparison failed" —
    the comparison checks then pass with a note rather than blocking a first
    commit that has no baseline by definition.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--baseline-ref",
        default="HEAD",
        help="git ref holding the currently published data (default: HEAD)",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=None,
        help="also require meta.json to have been written this recently — use in CI "
        "to catch a run that crashed before writing its output (default: off)",
    )
    args = parser.parse_args(argv)

    screener_path = args.data_dir / "screener.json"
    meta_path = args.data_dir / "meta.json"
    for path in (screener_path, meta_path):
        if not path.is_file():
            print(f"FAIL  missing  {path} was not written", file=sys.stderr)
            return 1

    raw = screener_path.read_bytes()
    try:
        screener = json.loads(raw)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAIL  parse  {exc}", file=sys.stderr)
        return 1

    try:
        relative = screener_path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        # `--data-dir` pointing outside the repository: there is no committed
        # version of a file git does not track, so the comparison checks note
        # that and pass rather than the whole gate crashing.
        relative = None
    baseline_raw = committed_blob(args.baseline_ref, relative) if relative else None
    baseline_screener = None
    if baseline_raw:
        try:
            baseline_screener = json.loads(baseline_raw)
        except json.JSONDecodeError:
            # A corrupt committed file is not this run's problem, and must not
            # block this run's good data from replacing it.
            print("note  committed screener.json does not parse; comparing nothing")
            baseline_raw = None

    findings = run_checks(
        screener=screener,
        meta=meta,
        size=len(raw),
        baseline_screener=baseline_screener,
        baseline_size=len(baseline_raw) if baseline_raw else None,
        max_age_hours=args.max_age_hours,
    )

    for finding in findings:
        print(f"{'ok  ' if finding.ok else 'FAIL'}  {finding.name}: {finding.detail}")

    failures = [f for f in findings if not f.ok]
    if failures:
        print(
            f"\n{len(failures)} check(s) failed — refusing to commit. "
            "The run's output is still on disk; inspect it before publishing.",
            file=sys.stderr,
        )
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
