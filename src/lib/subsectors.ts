/**
 * Subsector peer comparison (SPEC §8).
 *
 * The statistics here are computed over the companies that actually have a
 * figure, never over the whole subsector with nulls read as zero. A median that
 * quietly counts a suppressed value as zero would drag every summary toward the
 * floor and make the least-measurable subsectors look like the worst-performing
 * ones. Every summary therefore carries `n` alongside it.
 */
import type { CompanyRow, MetricResult } from "./screener";

export interface SubsectorMeta {
  slug: string;
  label: string;
  /** What the grouping means, so a reader is not guessing from the slug. */
  blurb: string;
}

export const SUBSECTORS: Record<string, SubsectorMeta> = {
  vaccines_infectious_disease: {
    slug: "vaccines-infectious-disease",
    label: "Vaccines and infectious disease",
    blurb:
      "Vaccine developers and anti-infectives. The anchor of this universe: pricing, tender and procurement structures and national immunisation decisions are readable from the filings in a way most sectors are not.",
  },
  large_cap_pharma: {
    slug: "large-cap-pharma",
    label: "Large-cap pharma",
    blurb:
      "Diversified originators with marketed portfolios across several therapeutic areas. Present largely as context for the smaller names.",
  },
  commercial_biotech: {
    slug: "commercial-biotech",
    label: "Commercial biotech",
    blurb: "Biotechnology companies with approved products and recurring revenue.",
  },
  clinical_stage_biotech: {
    slug: "clinical-stage-biotech",
    label: "Clinical-stage biotech",
    blurb:
      "Pre-commercial developers. Cash runway is the metric that matters most here, and R&D intensity is measured against operating expenses rather than revenue where there is no revenue to measure against.",
  },
  medtech: {
    slug: "medtech",
    label: "Medical technology",
    blurb:
      "Device makers. Their trials are pivotal, feasibility or post-market rather than phased, so pipeline depth is not applicable and is reported as null rather than zero.",
  },
  diagnostics: {
    slug: "diagnostics",
    label: "Diagnostics",
    blurb: "Laboratory services and diagnostic testing.",
  },
  life_science_tools: {
    slug: "life-science-tools",
    label: "Life science tools",
    blurb:
      "Instruments, reagents and research services. They sell to drug developers rather than developing drugs, so most sponsor no trials of their own.",
  },
  payer: {
    slug: "payer",
    label: "Payers",
    blurb: "Health insurers and pharmacy benefit managers.",
  },
  provider: { slug: "provider", label: "Providers", blurb: "Hospital and care-delivery operators." },
  hcit: {
    slug: "hcit",
    label: "Health IT",
    blurb: "Software and data businesses serving healthcare.",
  },
  distributor: {
    slug: "distributor",
    label: "Distributors",
    blurb: "Pharmaceutical and medical-product wholesalers.",
  },
};

export function metaFor(subsector: string): SubsectorMeta {
  return (
    SUBSECTORS[subsector] ?? {
      slug: subsector.replace(/_/g, "-"),
      label: subsector.replace(/_/g, " "),
      blurb: "",
    }
  );
}

export function subsectorBySlug(slug: string): string | undefined {
  return Object.entries(SUBSECTORS).find(([, m]) => m.slug === slug)?.[0];
}

// --------------------------------------------------------------------------- //
// Metrics shown on these pages
// --------------------------------------------------------------------------- //

export interface MetricSpec {
  key: string;
  label: string;
  unit: string;
  /** Which end of the distribution reads as "better", for labelling only. */
  direction: "higher" | "lower" | "neutral";
}

export const METRICS: MetricSpec[] = [
  { key: "revenue_ttm", label: "Revenue TTM", unit: "USD", direction: "neutral" },
  { key: "revenue_growth_yoy", label: "Revenue growth YoY", unit: "fraction", direction: "higher" },
  { key: "ocf_margin", label: "OCF margin", unit: "fraction", direction: "higher" },
  { key: "net_margin", label: "Net margin", unit: "fraction", direction: "higher" },
  { key: "operating_margin", label: "Operating margin", unit: "fraction", direction: "higher" },
  { key: "rnd_ttm", label: "R&D TTM", unit: "USD", direction: "neutral" },
  { key: "rnd_intensity", label: "R&D intensity", unit: "fraction", direction: "neutral" },
  { key: "net_cash", label: "Net cash", unit: "USD", direction: "higher" },
  { key: "cash_runway_quarters", label: "Cash runway", unit: "quarters", direction: "higher" },
  { key: "active_trials", label: "Active trials", unit: "count", direction: "neutral" },
  { key: "phase_3_trials", label: "Phase 3 trials", unit: "count", direction: "neutral" },
  { key: "pipeline_depth_score", label: "Pipeline depth", unit: "weighted", direction: "higher" },
  { key: "pipeline_concentration", label: "Pipeline concentration", unit: "HHI", direction: "lower" },
  { key: "clinical_momentum", label: "Clinical momentum", unit: "trials", direction: "higher" },
  { key: "discontinuation_rate", label: "Discontinuation rate", unit: "fraction", direction: "lower" },
];

/** The subset shown as columns in the ranked table; the rest appear in the distribution. */
export const RANKED_COLUMNS = [
  "revenue_ttm",
  "revenue_growth_yoy",
  "ocf_margin",
  "rnd_intensity",
  "cash_runway_quarters",
  "active_trials",
  "pipeline_depth_score",
];

export function valueOf(row: CompanyRow, key: string): number | null {
  const raw = (row as any)[key];
  if (raw && typeof raw === "object") return (raw as MetricResult).value ?? null;
  return typeof raw === "number" ? raw : null;
}

/** Reason a company has no figure, so an absence can be explained rather than blank. */
export function reasonsFor(row: CompanyRow, key: string): string[] {
  const raw = (row as any)[key];
  if (raw && typeof raw === "object") return (raw as MetricResult).suppressed_by ?? [];
  return [];
}

export interface Summary {
  spec: MetricSpec;
  n: number;
  total: number;
  min: number | null;
  median: number | null;
  max: number | null;
  minTicker: string | null;
  maxTicker: string | null;
  /** Why the companies without a figure do not have one, most common first. */
  absences: { reason: string; count: number }[];
}

/**
 * Distribution of one metric across a subsector.
 *
 * The median for an even count is the mean of the two middle values, which is
 * the conventional definition but does produce a number no company reported.
 * It is labelled as a summary statistic for that reason; every figure in the
 * ranked table below is a company's own.
 */
export function summarise(rows: CompanyRow[], spec: MetricSpec): Summary {
  const scored = rows
    .map((r) => ({ ticker: r.ticker, v: valueOf(r, spec.key) }))
    .filter((x): x is { ticker: string; v: number } => x.v !== null)
    .sort((a, b) => a.v - b.v);

  const counts = new Map<string, number>();
  for (const row of rows) {
    if (valueOf(row, spec.key) !== null) continue;
    const reasons = reasonsFor(row, spec.key);
    const reason = reasons.length ? reasons[0] : "no_figure";
    counts.set(reason, (counts.get(reason) ?? 0) + 1);
  }

  if (scored.length === 0) {
    return {
      spec,
      n: 0,
      total: rows.length,
      min: null,
      median: null,
      max: null,
      minTicker: null,
      maxTicker: null,
      absences: [...counts].map(([reason, count]) => ({ reason, count })).sort((a, b) => b.count - a.count),
    };
  }

  const mid = Math.floor(scored.length / 2);
  const median =
    scored.length % 2 === 1 ? scored[mid].v : (scored[mid - 1].v + scored[mid].v) / 2;

  return {
    spec,
    n: scored.length,
    total: rows.length,
    min: scored[0].v,
    median,
    max: scored[scored.length - 1].v,
    minTicker: scored[0].ticker,
    maxTicker: scored[scored.length - 1].ticker,
    absences: [...counts].map(([reason, count]) => ({ reason, count })).sort((a, b) => b.count - a.count),
  };
}

/** Rank by a metric, with companies lacking a figure always last. */
export function rankBy(rows: CompanyRow[], key: string): CompanyRow[] {
  return [...rows].sort((a, b) => {
    const av = valueOf(a, key);
    const bv = valueOf(b, key);
    if (av === null && bv === null) return a.ticker.localeCompare(b.ticker);
    if (av === null) return 1;
    if (bv === null) return -1;
    if (av !== bv) return bv - av;
    return a.ticker.localeCompare(b.ticker);
  });
}
