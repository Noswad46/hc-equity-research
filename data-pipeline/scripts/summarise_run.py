"""One-line-per-fact summary of a pipeline run, for the refresh commit message.

`git log` is the cheapest place to notice a slow degradation — a company that
has been stale for three weeks, a universe that quietly shrank. Putting the
counts in the commit body means spotting it takes no tooling at all.

Writes to stdout. Prints nothing rather than failing if `meta.json` is missing
or malformed: this runs inside the commit step, and a bad summary must not cost
a good refresh its commit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_META = REPO_ROOT / "src" / "data" / "meta.json"


def summarise(meta: Mapping[str, Any]) -> str:
    edgar = (meta.get("sources") or {}).get("edgar") or {}
    failed = edgar.get("companies_failed") or []
    carried = edgar.get("companies_carried_stale") or []
    dropped = edgar.get("companies_dropped") or []
    trials = (meta.get("sources") or {}).get("clinicaltrials") or {}

    lines = [
        f"{edgar.get('companies_ok', 0)} of {meta.get('universe_size', 0)} companies fetched.",
        f"{trials.get('studies_indexed', 0)} studies indexed "
        f"(registry as of {trials.get('as_of', 'unknown')}).",
    ]

    def name_them(label: str, entries: Sequence[Mapping[str, Any]]) -> None:
        if not entries:
            return
        tickers = ", ".join(str(e.get("ticker", "?")) for e in entries)
        lines.append(f"{label}: {tickers}")

    name_them("Failed", failed)
    name_them("Carried forward on previous figures", carried)
    name_them("Dropped after repeated failures", dropped)

    if not failed:
        lines.append("No failures.")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    path = Path(argv[0]) if argv else DEFAULT_META
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    print(summarise(meta))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
