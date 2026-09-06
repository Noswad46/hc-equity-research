# Healthcare Equity Screener

A public, static screener and company-profile site covering US-listed healthcare
companies, combining SEC financial fundamentals with clinical-pipeline and
regulatory data. See [`SPEC.md`](SPEC.md) for the full build specification.

**Status: Milestone 1.** EDGAR fetch and quarterly assembly, with tests against
known figures. No site pages yet.

## What exists

```
data-pipeline/
├── universe.yaml              # 10 tickers — hand-maintained coverage list
├── sources/edgar.py           # SEC companyfacts client
├── transform/fundamentals.py  # tag resolution, YTD -> discrete quarters
└── tests/                     # 136 tests, real and synthetic fixtures
```

Revenue, R&D and operating cash flow are resolved through the fallback chains in
SPEC §5.1 and converted from year-to-date filings into discrete quarters. Every
value records the XBRL tag it came from and whether it was reported directly or
derived by differencing.

## Running it

Python 3.11+.

```sh
cd data-pipeline
python -m venv .venv && .venv/bin/python -m pip install -r requirements.txt

# SEC rejects requests without a User-Agent naming a real person and email.
export SEC_USER_AGENT="Your Name you@example.com"

.venv/bin/python sources/edgar.py     # fetch the universe into cache/
.venv/bin/python -m pytest            # 136 tests, no network access
```

## Known data issues

These are real properties of the filings, found while building M1. Each is
detected and flagged rather than silently corrected — see the module docstring in
`transform/fundamentals.py` for the reasoning.

**The SPEC §5.1 R&D chain has one entry, and Pfizer and J&J do not use it.** Both
tag R&D as `ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost`. Pfizer
resolves to no R&D at all; J&J resolves to annual figures only, so no quarters.
The chain is implemented exactly as specified rather than widened silently; the
resolution names the near-miss tag instead. Widening it is a one-line change to
`CONCEPT_CHAINS`, but it changes what "R&D" means and should be a deliberate call.

**Pfizer's two revenue tags are not interchangeable.** They agree on every
quarterly and year-to-date period and disagree *only* on annuals: Pfizer uses
`RevenueFromContractWithCustomerExcludingAssessedTax` for total revenue in its
10-Qs, but for the narrower revenue-from-contracts subtotal in the 10-K. A Q4
derived as annual-minus-nine-months therefore absorbs the whole difference —
$15.8bn for Q4 2022, against the $25.1bn the same filing supports under
`Revenues`. `detect_tag_divergence` finds the disagreeing periods and marks every
quarter derived from one. Affects Q4 2021, 2022 and 2023.

**Restated annuals sitting above unrestated quarters.** Merck's FY2020 was
restated for the Organon spin-off and Becton Dickinson's for the Embecta
separation, so four quarters no longer sum to the year. `reconcile_fiscal_years`
checks every tileable fiscal year and flags the mismatches.

**IFRS filers are out of scope.** GSK, AstraZeneca, Sanofi and BioNTech file 20-F
under the `ifrs-full` taxonomy, so the us-gaap chains return nothing for them.
They are deliberately excluded from `universe.yaml`. Note that BioNTech publishes
an `ifrs-full:ResearchAndDevelopmentExpense` whose local name collides with the
us-gaap tag, so facts are matched on taxonomy, never on tag name alone.

**Some quarters are legitimately empty.** Where a filer switches tags mid-year —
Becton Dickinson's operating cash flow in FY2026 — deriving the missing quarter
would mean subtracting one tag from another. That is refused, and the quarter is
left null. A missing figure is a better failure than a confident wrong one.

## Disclaimer

This is a personal project for research and educational purposes. It presents
publicly available data from SEC EDGAR, ClinicalTrials.gov and openFDA, together
with metrics derived from that data. Nothing here is investment advice, a
recommendation, or an offer to buy or sell any security. Figures may be
incomplete, delayed, or incorrect.
