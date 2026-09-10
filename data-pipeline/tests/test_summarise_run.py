"""The refresh commit message.

`git log` is where a slow degradation shows up — a company stale three weeks
running, a universe that quietly shrank — so the counts have to be in the
message and have to name names. This runs inside the commit step, so it also
must never be the reason a good refresh fails to commit.
"""

from __future__ import annotations

from scripts.summarise_run import main, summarise


def meta(**edgar) -> dict:
    return {
        "universe_size": 58,
        "sources": {
            "edgar": {"companies_ok": 58, **edgar},
            "clinicaltrials": {"studies_indexed": 15_759, "as_of": "2026-09-10"},
        },
    }


def test_a_clean_run_says_so():
    text = summarise(meta())
    assert "58 of 58 companies fetched." in text
    assert "15759 studies indexed (registry as of 2026-09-10)." in text
    assert "No failures." in text


def test_failures_are_named_not_just_counted():
    text = summarise(
        meta(companies_ok=56, companies_failed=[{"ticker": "PFE"}, {"ticker": "MRK"}])
    )
    assert "56 of 58 companies fetched." in text
    assert "Failed: PFE, MRK" in text
    assert "No failures." not in text


def test_carried_and_dropped_companies_are_called_out_separately():
    """The distinction is the whole point of the bound: one is recoverable."""
    text = summarise(
        meta(
            companies_failed=[{"ticker": "PFE"}, {"ticker": "SIGA"}],
            companies_carried_stale=[{"ticker": "PFE"}],
            companies_dropped=[{"ticker": "SIGA"}],
        )
    )
    assert "Carried forward on previous figures: PFE" in text
    assert "Dropped after repeated failures: SIGA" in text


def test_a_missing_meta_file_is_silent_and_successful(tmp_path, capsys):
    """A bad summary must not cost a good refresh its commit."""
    assert main([str(tmp_path / "nope.json")]) == 0
    assert capsys.readouterr().out == ""


def test_an_unparseable_meta_file_is_silent_and_successful(tmp_path, capsys):
    path = tmp_path / "meta.json"
    path.write_text("{truncated", encoding="utf-8")

    assert main([str(path)]) == 0
    assert capsys.readouterr().out == ""
