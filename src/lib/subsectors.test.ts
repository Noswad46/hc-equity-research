/**
 * Subsector statistics.
 *
 * The null handling is what these tests are for. A median that reads a
 * suppressed value as zero would drag every summary toward the floor and make
 * the subsectors with the least-measurable companies look like the
 * worst-performing ones — the same class of error as sorting `n/m` as zero,
 * one layer up.
 */
import { describe, expect, it } from "vitest";
import { METRICS, metaFor, rankBy, subsectorBySlug, summarise, valueOf } from "./subsectors";
import type { CompanyRow, MetricResult } from "./screener";

function metric(value: number | null, suppressedBy: string[] = []): MetricResult {
  return { name: "m", value, suppressed: suppressedBy.length > 0, suppressed_by: suppressedBy, flags: [], period_ends: [] };
}

function row(ticker: string, overrides: Partial<CompanyRow> = {}): CompanyRow {
  return {
    ticker,
    cik: "0000000001",
    name: `${ticker} Inc.`,
    subsector: "commercial_biotech",
    therapeutic_focus: [],
    fiscal_period_end: "2026-06-30",
    revenue_ttm: 100,
    rnd_ttm: 10,
    ocf_ttm: 5,
    operating_income_ttm: 20,
    net_income_ttm: 15,
    cash: 50,
    revenue_growth_yoy: metric(0.1),
    operating_margin: metric(0.2),
    ocf_margin: metric(0.05),
    net_margin: metric(0.15),
    net_cash: metric(40),
    cash_runway_quarters: metric(null, ["operating_cash_flow_positive"]),
    rnd_intensity: metric(0.1),
    active_trials: 3,
    phase_3_trials: 1,
    pipeline_depth_score: metric(10),
    pipeline_concentration: metric(0.3),
    clinical_momentum: metric(1),
    discontinuation_rate: metric(0.2),
    rnd_per_late_stage_programme: metric(null),
    data_quality_flags: [],
    ...overrides,
  } as CompanyRow;
}

const revenue = METRICS.find((m) => m.key === "revenue_ttm")!;
const runway = METRICS.find((m) => m.key === "cash_runway_quarters")!;

describe("summarise", () => {
  it("computes min, median and max over an odd count", () => {
    const s = summarise(
      [row("A", { revenue_ttm: 10 }), row("B", { revenue_ttm: 30 }), row("C", { revenue_ttm: 20 })],
      revenue,
    );
    expect([s.min, s.median, s.max]).toEqual([10, 20, 30]);
    expect(s.n).toBe(3);
  });

  it("takes the mean of the two middle values on an even count", () => {
    const s = summarise(
      [row("A", { revenue_ttm: 10 }), row("B", { revenue_ttm: 20 })],
      revenue,
    );
    expect(s.median).toBe(15);
  });

  it("excludes nulls from the statistics rather than reading them as zero", () => {
    const s = summarise(
      [row("A", { revenue_ttm: 10 }), row("B", { revenue_ttm: null }), row("C", { revenue_ttm: 20 })],
      revenue,
    );
    expect(s.n).toBe(2);
    expect(s.total).toBe(3);
    expect(s.min).toBe(10); // not 0
    expect(s.median).toBe(15); // not 10, which is what a zero would make it
  });

  it("reports every metric as null when nobody has a figure", () => {
    const s = summarise(
      [row("A", { pipeline_depth_score: metric(null, ["phase_not_applicable"]) })],
      METRICS.find((m) => m.key === "pipeline_depth_score")!,
    );
    expect(s.n).toBe(0);
    expect([s.min, s.median, s.max]).toEqual([null, null, null]);
    expect(s.absences).toEqual([{ reason: "phase_not_applicable", count: 1 }]);
  });

  it("counts why the missing figures are missing", () => {
    const s = summarise(
      [
        row("A", { cash_runway_quarters: metric(4) }),
        row("B"),
        row("C"),
        row("D", { cash_runway_quarters: metric(null, ["restricted_cash_not_separable"]) }),
      ],
      runway,
    );
    expect(s.n).toBe(1);
    expect(s.absences).toEqual([
      { reason: "operating_cash_flow_positive", count: 2 },
      { reason: "restricted_cash_not_separable", count: 1 },
    ]);
  });

  it("names the companies holding each end of the range", () => {
    const s = summarise([row("LOW", { revenue_ttm: 1 }), row("HIGH", { revenue_ttm: 9 })], revenue);
    expect([s.minTicker, s.maxTicker]).toEqual(["LOW", "HIGH"]);
  });

  it("handles an empty subsector without throwing", () => {
    const s = summarise([], revenue);
    expect(s.n).toBe(0);
    expect(s.total).toBe(0);
  });
});

describe("rankBy", () => {
  it("orders descending with missing figures last in either case", () => {
    const rows = [
      row("MID", { revenue_ttm: 20 }),
      row("NONE", { revenue_ttm: null }),
      row("TOP", { revenue_ttm: 90 }),
    ];
    expect(rankBy(rows, "revenue_ttm").map((r) => r.ticker)).toEqual(["TOP", "MID", "NONE"]);
  });

  it("breaks ties on ticker so the order is stable", () => {
    const rows = [row("ZZ", { revenue_ttm: 5 }), row("AA", { revenue_ttm: 5 })];
    expect(rankBy(rows, "revenue_ttm").map((r) => r.ticker)).toEqual(["AA", "ZZ"]);
  });
});

describe("slugs", () => {
  it("round-trips every known subsector", () => {
    for (const key of Object.keys(
      // every subsector the pages can generate
      { vaccines_infectious_disease: 1, large_cap_pharma: 1, medtech: 1, payer: 1, hcit: 1 },
    )) {
      expect(subsectorBySlug(metaFor(key).slug)).toBe(key);
    }
  });

  it("degrades gracefully on an unknown subsector", () => {
    expect(metaFor("brand_new_thing").slug).toBe("brand-new-thing");
  });
});

describe("valueOf", () => {
  it("reads both plain numbers and metric objects", () => {
    expect(valueOf(row("A", { active_trials: 7 }), "active_trials")).toBe(7);
    expect(valueOf(row("A", { net_margin: metric(0.5) }), "net_margin")).toBe(0.5);
    expect(valueOf(row("A", { net_margin: metric(null, ["x"]) }), "net_margin")).toBeNull();
  });
});
