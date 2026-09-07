# Healthcare Equity Screener

A public, static screener and company-profile site covering US-listed healthcare
companies, combining SEC financial fundamentals with clinical-pipeline and
regulatory data. See [`SPEC.md`](SPEC.md) for the full build specification.

**Status: Milestone 1 complete.** EDGAR fetch and quarterly assembly, with tests
against known figures. The Astro site is scaffolded but has no real pages yet.

## What exists

```
data-pipeline/
├── universe.yaml              # 10 tickers — hand-maintained coverage list
├── sources/edgar.py           # SEC companyfacts client
├── transform/fundamentals.py  # tag resolution, YTD -> discrete quarters
└── tests/                     # 184 tests, real and synthetic fixtures
content/
├── methodology/               # coverage and exclusion rationale
└── subsectors/                # per-subsector notes
src/pages/                     # Astro scaffold — placeholder index only
```

### A note on the Astro version

SPEC §2 specifies Astro 5. The project is scaffolded on **Astro 7**, which is
what `npm create astro@latest` installs today. The reasons SPEC gives for
choosing Astro — static output, islands architecture, familiarity — all still
hold, and the build is confirmed static. Pinning back to 5 is a one-line change
to `package.json` if the version in SPEC was deliberate rather than simply
current at the time of writing.

Revenue, R&D and operating cash flow are resolved from the candidate tags in
SPEC §5.1 and converted from year-to-date filings into discrete quarters. Every
value records the XBRL tag it came from, whether it was reported directly or
derived by differencing, and what it measures where the tags differ on that.

Three rules keep derived figures honest. Tags are resolved **per period**, not
per company, since filers migrate tags mid-life. **Arithmetic never crosses
tags** — quarters are derived inside one tag's fact set, and only finished
quarters are compared. **Restatements resolve to the most recently filed value**,
on both sides of every subtraction.

### Two departures from SPEC §5.1

**Revenue is a candidate set, not a fallback chain.** SPEC orders
`RevenueFromContractWithCustomerExcludingAssessedTax` first. That is wrong for
pharma: alliance revenue, royalties, collaboration income and grant revenue sit
outside ASC 606, so `Revenues` is the income statement total and the
contracts-with-customers tag is a *component* of it. Where several candidates
cover a period and each is internally consistent, the largest wins — a total is
by definition at least as large as any component. This resolves Pfizer's Q4 2022
revenue to $25.1bn rather than $15.8bn.

The consistency gate is load-bearing. Emergent reports a Q2 2021 component
*exceeding* its own total, which is impossible; that tag's quarters never tile a
fiscal year so it cannot be reconciled, while `Revenues` reconciles exactly, so
`Revenues` wins despite being smaller. Ranking on size alone would take the
anomaly.

**The R&D chain carries both IPR&D bases.** SPEC lists one tag, which Pfizer and
J&J do not use, leaving them with no R&D at all.
`ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost` is now read too —
but the two are not interchangeable. Moderna's `ResearchAndDevelopmentExpense`
includes acquired IPR&D; Pfizer's and J&J's excludes it, and IPR&D charges are
lumpy and deal-driven. Every value carries its `measurement_basis` and **nothing
normalises between them**. R&D intensity across a mixed basis is not comparable,
and deciding what to do about that belongs with the derived metrics.

### Flags suppress, not just annotate

A period flagged `restated_fiscal_year` disqualifies any growth or comparison
metric spanning it. Merck's FY2020 quarters are real filed figures and are still
emitted, but a year-on-year comparison across them measures the Organon spin-off
rather than trading, so `growth()` returns null with a reason rather than a
footnoted percentage. `guard_metric` is the general mechanism; route any SPEC §6
metric through it rather than reading `PeriodValue.val` directly.

Annotating alone would solve the confident-looking-wrong-number problem at the
fact layer and let it reappear at the metric layer, where a dropped footnote is
invisible and a null is not.

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

**Pfizer's Q4 2021 revenue cannot be moved to the `Revenues` basis.** Under that
tag Pfizer filed only the FY2021 annual — no year-to-date facts for 2021 at all —
so no Q4 2021 candidate exists to select. Producing one would mean subtracting a
contracts-with-customers nine-month figure from a `Revenues` annual, and that
cross-tag subtraction is what created the $9bn error in the first place. The
quarter stays on the component basis, flagged `tag_basis_uncertain`. Q4 2022 and
Q4 2023 both resolve correctly.

`detect_tag_divergence` still reports the disagreeing periods even where
selection now picks correctly, because a divergence that large is worth seeing
downstream.

**Restated annuals sitting above unrestated quarters.** Merck's FY2020 was
restated for the Organon spin-off and Becton Dickinson's for the Embecta
separation, so four quarters no longer sum to the year. `reconcile_fiscal_years`
checks every tileable fiscal year, flags the mismatches, and those flags suppress
growth metrics spanning them.

**Pfizer's 2011 period boundaries overlap.** Its Q1 2011 ends 3 April on the
52/53-week calendar while its Q2 2011 facts declare a start of 1 April, so the
two quarters share two days. `resolve_overlaps` keeps the better-provenanced one,
which costs a quarter of 2011 history and leaves a flagged hole. Only Pfizer, only
2011; every series is contiguous from 2018 onward. Older gaps elsewhere (Merck
2011–17, J&J 2012–17) are periods those filers simply did not tag.

**IFRS filers are excluded on comparability grounds, not just plumbing.** GSK,
AstraZeneca, Sanofi and BioNTech report under IFRS. Under IAS 38 qualifying
development costs are capitalised and amortised, while US GAAP expenses
essentially all R&D as incurred — so R&D intensity and cash runway measure
different things on the two bases, and no adjustment available from
`companyfacts` fixes that. Several of them also file annually on 20-F rather than
quarterly, so the discrete quarterly series does not exist for them at all.

BioNTech publishes an `ifrs-full:ResearchAndDevelopmentExpense` whose local name
is identical to the us-gaap tag, so facts are matched on taxonomy, never on tag
name alone. Full reasoning in `content/methodology/coverage-exclusions.md`; the
vaccines subsector page carries a "not covered, and why" note, since GSK and
Sanofi being absent is a visible hole on a vaccines-focused page.

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
