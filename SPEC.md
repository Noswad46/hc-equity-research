# Healthcare Equity Screener — Build Specification

**Working title:** TBD
**Owner:** Euan
**Purpose:** A public, static, data-driven screener and company-profile site covering US-listed healthcare companies. Combines SEC financial fundamentals with clinical-pipeline and regulatory data to produce metrics that generic screeners don't show.

This document is the starting context for the build. Endpoint details are accurate as of writing but should be verified against live responses before being relied on.

---

## 1. Goals and non-goals

### Goals

1. Let a visitor filter and sort a curated healthcare universe on both financial and clinical-operating metrics in one table.
2. Give every covered company a profile page that reads like the quantitative half of a research note.
3. Publish the derived-metric definitions openly, so the analysis is auditable.
4. Run entirely as a static site with zero hosting cost and no runtime secrets.

### Non-goals for v1

- Real-time or intraday pricing.
- Full global coverage. The universe is curated and deliberately small.
- User accounts, saved screens, watchlists, or any server-side state.
- Written research notes. Long-form commentary lives on the existing blog, not here.
- Any output framed as a recommendation, rating, or price target.

---

## 2. Stack

| Layer | Choice | Rationale |
|---|---|---|
| Data pipeline | Python 3.11+ | Best libraries for XBRL and HTTP; runs in CI, not in the browser |
| Site framework | Astro 5 | Already familiar; static output; islands architecture suits one interactive page |
| Interactive island | React + TypeScript | Only for the screener table and charts |
| Charts | Recharts | Pairs with the React island; adequate for time series and bar/stacked charts |
| Styling | Plain CSS with custom properties | Consistent with the existing blog; no Tailwind |
| Hosting | Cloudflare Pages | Same as existing setup; free; deploys on push |
| Automation | GitHub Actions | Scheduled pipeline run, commits refreshed JSON |

**Key architectural decision:** all data fetching and computation happens at build time. The browser receives static JSON. There is no backend, no API key in the client, and no rate limit exposure to visitors.

---

## 3. Repository structure

```
healthcare-equity-screener/
├── data-pipeline/
│   ├── universe.yaml              # curated coverage list — hand-maintained
│   ├── run.py                     # orchestrator
│   ├── requirements.txt
│   ├── sources/
│   │   ├── edgar.py               # SEC XBRL company facts
│   │   ├── clinicaltrials.py      # ClinicalTrials.gov API v2
│   │   ├── openfda.py             # approvals, labels, 510(k)/PMA
│   │   └── prices.py              # optional, see §5.5
│   ├── transform/
│   │   ├── fundamentals.py        # XBRL tag resolution, TTM assembly
│   │   ├── clinical.py            # pipeline aggregation
│   │   └── derive.py              # derived metrics (§6)
│   ├── cache/                     # raw API responses, gitignored
│   └── tests/
├── src/
│   ├── data/                      # pipeline output — COMMITTED to the repo
│   │   ├── screener.json
│   │   ├── meta.json
│   │   └── companies/
│   │       └── {TICKER}.json
│   ├── components/
│   │   ├── Screener.tsx           # the React island
│   │   ├── FilterPanel.tsx
│   │   ├── DataTable.tsx
│   │   └── charts/
│   ├── layouts/
│   ├── pages/
│   │   ├── index.astro
│   │   ├── screener.astro
│   │   ├── companies/[ticker].astro
│   │   ├── subsectors/[slug].astro
│   │   ├── methodology.astro
│   │   └── about.astro
│   └── styles/
├── .github/workflows/refresh-data.yml
├── astro.config.mjs
└── README.md
```

Committing generated JSON to the repo is intentional. It keeps builds reproducible, makes data changes visible in git history, and means a Cloudflare rebuild never depends on a third-party API being up.

---

## 4. Coverage universe

### Sizing

40–60 tickers for v1. A narrow, complete universe is more credible than a broad, half-populated one, and it's far easier to defend in an interview.

### Recommended anchor

Start where the domain knowledge is strongest rather than where the market cap is largest. Vaccines and infectious disease is a genuine edge — pricing dynamics, tender and procurement structures, national immunisation programme decisions, and HTA-driven access are all things most equity analysts handle badly and are directly readable from a health economics background. A universe built around vaccines, anti-infectives, and adjacent commercial-stage biotech makes the site distinctive in a way a generic large-cap pharma screen would not.

Reasonable v1 shape: a vaccines and infectious-disease core, plus a comparison set of large-cap pharma so the metrics have context.

### `universe.yaml` schema

```yaml
- ticker: PFE
  cik: "0000078003"
  name: Pfizer Inc.
  subsector: large_cap_pharma        # see enum below
  therapeutic_focus: [vaccines, oncology, immunology]
  ct_sponsor_names:                  # exact ClinicalTrials.gov lead sponsor strings
    - "Pfizer"
  fda_applicant_names:               # exact openFDA applicant strings
    - "PFIZER INC"
  index_membership: [sp500]
  notes: ""
```

**Subsector enum:** `large_cap_pharma`, `commercial_biotech`, `clinical_stage_biotech`, `vaccines_infectious_disease`, `medtech`, `diagnostics`, `life_science_tools`, `payer`, `provider`, `hcit`, `distributor`.

**Critical gotcha:** sponsor and applicant names in ClinicalTrials.gov and openFDA do not match tickers or SEC registrant names, and subsidiaries file under their own names (acquisitions are the worst case — trials stay under the acquired entity's name for years). These mappings must be curated by hand in `universe.yaml` and reviewed whenever a name is added. Do not attempt fuzzy matching; it produces silent, plausible-looking errors.

---

## 5. Data sources

### 5.1 SEC EDGAR — fundamentals

Public domain, no key, no redisplay restriction.

| Purpose | Endpoint |
|---|---|
| Ticker → CIK map | `https://www.sec.gov/files/company_tickers.json` |
| All XBRL facts for a filer | `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` |
| Single concept time series | `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/{Tag}.json` |
| Filing history, shares outstanding | `https://data.sec.gov/submissions/CIK##########.json` |

Requirements: CIK is zero-padded to 10 digits. A `User-Agent` header containing a real name and email address is mandatory — requests without it are rejected. Rate limit is 10 requests/second; throttle accordingly.

**Tag resolution.** Companies tag the same concept differently, so every concept needs an ordered fallback chain, and the chain that was used should be recorded in the output for auditability:

| Concept | Fallback chain |
|---|---|
| Revenue | `RevenueFromContractWithCustomerExcludingAssessedTax` → `Revenues` → `SalesRevenueNet` |
| R&D expense | `ResearchAndDevelopmentExpense` |
| Cash | `CashAndCashEquivalentsAtCarryingValue` |
| Short-term investments | `ShortTermInvestments` → `MarketableSecuritiesCurrent` → `AvailableForSaleSecuritiesDebtSecuritiesCurrent` |
| Operating cash flow | `NetCashProvidedByUsedInOperatingActivities` → `...ContinuingOperations` |
| Operating income | `OperatingIncomeLoss` |
| Net income | `NetIncomeLoss` |
| Debt | `LongTermDebtNoncurrent` + `LongTermDebtCurrent` |
| Shares outstanding | `dei:EntityCommonStockSharesOutstanding` (from submissions) → `CommonStockSharesOutstanding` |

**TTM gotcha — this will bite.** Income-statement and cash-flow facts in `companyfacts` carry `start`/`end` dates, and many 10-Q figures are year-to-date rather than discrete quarters. Q4 is almost never filed on its own. Deriving discrete quarters requires: take the annual figure from the 10-K, subtract the nine-month YTD figure to get Q4, and difference successive YTD figures to get Q2 and Q3. Filter facts by `form` (`10-K`, `10-Q`) and prefer the most recently filed value where a period has been restated. Write unit tests for this against two or three companies with known figures before trusting anything downstream.

### 5.2 ClinicalTrials.gov API v2 — pipeline

Base: `https://clinicaltrials.gov/api/v2/studies`

Useful parameters: `query.spons` (lead sponsor), `filter.overallStatus`, `fields` (restrict payload), `pageSize` (max 1000), `pageToken` (pagination cursor). No key required.

Fields to pull per study: `NCTId`, `BriefTitle`, `Phase`, `OverallStatus`, `Condition`, `InterventionName`, `InterventionType`, `EnrollmentCount`, `StudyType`, `StartDate`, `PrimaryCompletionDate`, `CompletionDate`, `LeadSponsorName`, `WhyStopped`.

Filter to `StudyType = INTERVENTIONAL` and to studies where the company is the *lead* sponsor, not a collaborator, or the counts will be inflated by investigator-initiated work.

### 5.3 openFDA — regulatory

Base: `https://api.fda.gov`

| Purpose | Endpoint |
|---|---|
| Drug approvals and applications | `/drug/drugsfda.json` |
| Product labels | `/drug/label.json` |
| Device 510(k) clearances | `/device/510k.json` |
| Device PMA approvals | `/device/pma.json` |

Rate limits are generous but real: roughly 240 requests/minute and 1,000/day without a key; a free key raises the daily ceiling substantially. Request a key and store it as a GitHub Actions secret.

For v1, openFDA is lower priority than EDGAR and ClinicalTrials.gov. Use it for approval counts and recent approval dates; defer label and adverse-event work.

### 5.4 CMS — reimbursement (optional, v2)

`https://data.cms.gov/data.json` indexes the available datasets. Medicare Part B and Part D drug spending give per-product US revenue visibility that isn't in segment reporting — a genuinely differentiated input, but the datasets are large and lag by one to two years. Defer to v2.

### 5.5 Prices and valuation — handle carefully

EDGAR gives fundamentals but not market data, so market cap and any valuation multiple requires a price source.

Most free tiers of commercial price APIs (Alpha Vantage, Financial Modeling Prep, Finnhub) restrict public redisplay of their data. Read the current terms before building market cap into a public page. Stooq's free CSV endpoint (`https://stooq.com/q/d/l/?s={ticker}.us&i=d`) is the common workaround for personal projects.

If licensing is unresolved, ship v1 without prices. Every metric in §6 except market cap and multiples is computable from EDGAR alone, and a screener built purely on operating and clinical metrics is arguably a more interesting object anyway.

---

## 6. Derived metrics

This section is the intellectual core of the site. Each metric must be defined precisely, computed transparently, and documented on the methodology page.

| Metric | Definition | Notes |
|---|---|---|
| Net cash | `cash + short_term_investments − total_debt` | Negative for leveraged large caps |
| Cash runway (quarters) | `(cash + ST investments) / mean(abs(quarterly OCF)) over trailing 4Q` | Null when trailing OCF is positive. The single most useful metric for clinical-stage names |
| R&D intensity | `R&D_ttm / revenue_ttm` | For pre-revenue names, use `R&D_ttm / opex_ttm` and flag the variant |
| R&D per late-stage programme | `R&D_ttm / count(active Phase 2 and 3 trials)` | Crude, but comparable within subsector; surfaces capital efficiency |
| Pipeline depth score | `1×Ph1 + 3×Ph2 + 8×Ph3 + 12×Ph4/registration`, counting active trials only | Transparent heuristic. Publish the weights; do not present it as proprietary |
| Pipeline concentration | HHI across therapeutic areas of active trials | High = single-asset risk |
| Clinical momentum | `trials started in trailing 12m − trials started in prior 12m` | Positive means the pipeline is expanding |
| Discontinuation rate | `terminated + withdrawn / (completed + terminated + withdrawn)`, all time | Noisy for small samples; suppress below 10 total trials |
| Gross / operating / OCF margin | Standard | |
| Revenue growth | TTM vs prior TTM | |

**Presentation rule:** every metric on a company page carries an as-of date and a source label. Any metric computed from a fallback tag chain other than the primary tag is footnoted. This is what separates a research tool from a scraper.

---

## 7. Output schemas

### `src/data/meta.json`

```json
{
  "generated_at": "2026-09-06T04:00:00Z",
  "universe_size": 52,
  "sources": {
    "edgar": { "fetched_at": "...", "companies_ok": 52, "companies_failed": [] },
    "clinicaltrials": { "fetched_at": "...", "studies_indexed": 4188 },
    "openfda": { "fetched_at": "..." }
  },
  "pipeline_version": "1.0.0"
}
```

### `src/data/screener.json`

One flat record per company — everything the screener table needs, nothing it doesn't. Target under 1 MB total so it can be loaded client-side in one request.

```json
{
  "generated_at": "2026-09-06T04:00:00Z",
  "companies": [
    {
      "ticker": "PFE",
      "cik": "0000078003",
      "name": "Pfizer Inc.",
      "subsector": "large_cap_pharma",
      "therapeutic_focus": ["vaccines", "oncology", "immunology"],
      "fiscal_period_end": "2026-06-30",
      "revenue_ttm": 0,
      "revenue_growth_yoy": 0.0,
      "rnd_ttm": 0,
      "operating_margin": 0.0,
      "ocf_ttm": 0,
      "net_cash": 0,
      "cash_runway_quarters": null,
      "rnd_intensity": 0.0,
      "active_trials": 0,
      "phase_3_trials": 0,
      "pipeline_depth_score": 0,
      "pipeline_concentration": 0.0,
      "clinical_momentum": 0,
      "data_quality_flags": []
    }
  ]
}
```

### `src/data/companies/{TICKER}.json`

Superset of the screener record, plus:

```json
{
  "quarterly": [
    { "period_end": "2026-06-30", "revenue": 0, "rnd": 0, "ocf": 0,
      "cash": 0, "operating_income": 0, "source_tags": { "revenue": "Revenues" } }
  ],
  "annual": [ "... same shape ..." ],
  "pipeline": {
    "active_trials_total": 0,
    "by_phase": { "phase_1": 0, "phase_2": 0, "phase_3": 0, "phase_4": 0, "not_applicable": 0 },
    "by_status": { "recruiting": 0, "active_not_recruiting": 0, "enrolling_by_invitation": 0 },
    "top_conditions": [ { "condition": "Pneumococcal Infections", "count": 0 } ],
    "upcoming_readouts": [
      { "nct_id": "NCT00000000", "title": "...", "phase": "PHASE3",
        "condition": "...", "primary_completion_date": "2027-03-01", "enrollment": 0 }
    ],
    "started_ttm": 0,
    "started_prior_ttm": 0,
    "discontinued_all_time": 0
  },
  "regulatory": {
    "approvals_last_5y": [ { "product": "...", "application_number": "...", "date": "..." } ]
  },
  "filings": [ { "form": "10-Q", "filed": "2026-08-05", "url": "https://www.sec.gov/..." } ]
}
```

---

## 8. Pages

### `/` — home

State plainly what the site is, what it covers, and where the data comes from. Then show something real immediately: a small set of live cuts from the current dataset (for example, shortest cash runway in the universe, largest positive clinical momentum, highest R&D intensity). Avoid a marketing hero with no data in it — for this audience the data *is* the pitch.

### `/screener` — the main page

- Sortable, filterable table, all filtering client-side.
- Filter panel: subsector (multi), therapeutic focus (multi), profitability (profitable / unprofitable), cash runway band, active Phase 3 count minimum, revenue band.
- Column presets: **Fundamentals**, **Cash & burn**, **Pipeline**. Presets matter — 20 columns at once is unreadable.
- URL-encoded filter state so a screen can be linked and shared.
- CSV export of the current view.
- Row click opens the company page.
- Sticky header and sticky first column; the table must survive 60 rows without becoming unusable.

### `/companies/[ticker]` — company profile

Statically generated for every ticker. Sections in order:

1. Header — name, ticker, subsector, fiscal period end, data as-of.
2. Financial snapshot — revenue, growth, margins, R&D, net cash, runway.
3. Trend charts — revenue and R&D by quarter; cash and OCF by quarter.
4. Pipeline — phase distribution bar, active trials table, upcoming primary completion dates.
5. Regulatory — recent approvals.
6. Sources — direct links to the underlying EDGAR filings and ClinicalTrials.gov queries.

### `/subsectors/[slug]`

Peer comparison within a subsector: distribution of each key metric, ranked table, medians. Cheap to build once the screener data exists, and makes the site feel deeper than one table.

### `/methodology`

Every derived metric, its formula, its source, its known limitations, and the update cadence. Ship this with v1, not later. For the audience that matters here, this page is the strongest signal on the site.

### `/about`

Who built it, why, and the disclaimer.

---

## 9. Design direction

The subject is clinical and financial data for a professional audience, so the design should read as an instrument rather than a publication. Density is a feature; whitespace-heavy marketing layouts would be wrong here.

**Proposed token system** — adjust freely, but decide deliberately rather than defaulting.

```css
:root {
  --ink:        #16222E;  /* deep blue-slate, primary text */
  --ink-muted:  #5A6B7A;  /* secondary text, axis labels */
  --field:      #EEF1F3;  /* table zebra, panel fills */
  --rule:       #D3DAE0;  /* hairlines, table borders */
  --paper:      #FFFFFF;
  --advance:    #0F7A6B;  /* positive delta, phase progression */
  --retreat:    #9B2C2C;  /* negative delta, discontinuation */
}
```

Green and red carry functional meaning here (direction of change, trial outcome), which justifies them; they should not appear as decoration anywhere else.

**Type.** Two families with distinct jobs, mirroring how the industry actually sets its documents: a serif for prose and page headings, because research notes are set in serif, and a grotesk with proper tabular figures for all data, because terminals are set in sans. Source Serif 4 and IBM Plex Sans are both free and both have the numeral support needed. Apply `font-variant-numeric: tabular-nums` to every numeric cell so columns align.

**Structure.** Rules and alignment do the organising work — no card shadows, no rounded containers around table sections. Right-align numbers, left-align labels. One accent moment per page at most.

**Motion.** Only in response to a user action: sort direction, filter application, row expansion. No scroll-triggered entrances.

**Quality floor.** Keyboard-navigable table, visible focus states, `prefers-reduced-motion` respected, readable on a phone even though the screener is a desktop-first experience.

---

## 10. Automation

`.github/workflows/refresh-data.yml`:

- Trigger: `schedule` weekly (fundamentals move quarterly, so weekly is generous) plus `workflow_dispatch` for manual runs.
- Steps: checkout → set up Python → install requirements → run `data-pipeline/run.py` → commit changes under `src/data/` if any → push.
- Secrets: `OPENFDA_API_KEY`, and the contact email used in the EDGAR `User-Agent`.
- Push to `main` triggers the Cloudflare Pages build automatically.

**Pipeline resilience:** a failure fetching one company must not fail the whole run. Catch per-company, record the failure in `meta.json`, and keep the previous good record for that ticker. A site that silently drops half its universe because one API hiccupped is worse than a stale one.

---

## 11. Build order

| Milestone | Deliverable |
|---|---|
| M1 | `universe.yaml` with 10 tickers; EDGAR fetch and TTM assembly working; tests passing against known figures |
| M2 | Static company pages rendering fundamentals from JSON; no charts, no screener |
| M3 | Screener island with filtering, sorting, column presets, URL state |
| M4 | ClinicalTrials.gov integration; pipeline metrics; phase charts |
| M5 | Expand universe to full size; subsector pages; methodology page |
| M6 | GitHub Action automation; Cloudflare deploy |
| M7 | Optional: openFDA regulatory data, prices and valuation multiples, CMS spending |

Do M1 properly before anything else. Every metric downstream inherits errors in the TTM assembly, and those errors are hard to spot once they're rendered as confident-looking numbers in a table.

---

## 12. Disclaimer

Required in the footer of every page and in full on `/about`:

> This site is a personal project for research and educational purposes. It presents publicly available data from SEC EDGAR, ClinicalTrials.gov, and openFDA, together with metrics derived from that data. Nothing here is investment advice, a recommendation, or an offer to buy or sell any security. Figures may be incomplete, delayed, or incorrect.

Given the target audience, also worth noting: if any employer's compliance policy governs personal publication about covered securities, check it before the site goes public.