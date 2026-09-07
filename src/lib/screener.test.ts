/**
 * Screener logic. The sorting rules matter most.
 *
 * `n/m` and `null` exist to keep names with unusable data out of the way. If
 * they sorted as zero or infinity they would occupy the top of a growth or
 * runway screen — which is the exact failure the suppression was introduced to
 * prevent, reappearing one layer up.
 */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_STATE,
  RUNWAY_BANDS,
  applyFilters,
  cellOf,
  compareRows,
  decodeState,
  encodeState,
  toCsv,
  type CompanyRow,
  type MetricResult,
} from "./screener";

function metric(value: number | null, suppressedBy: string[] = []): MetricResult {
  return {
    name: "m",
    value,
    suppressed: suppressedBy.length > 0,
    suppressed_by: suppressedBy,
    flags: [],
    period_ends: [],
  };
}

function row(overrides: Partial<CompanyRow> = {}): CompanyRow {
  return {
    ticker: "AAA",
    cik: "0000000001",
    name: "Alpha",
    subsector: "large_cap_pharma",
    therapeutic_focus: ["vaccines"],
    fiscal_period_end: "2026-06-30",
    revenue_ttm: 1000,
    rnd_ttm: 100,
    ocf_ttm: 50,
    operating_income_ttm: 200,
    cash: 500,
    revenue_growth_yoy: metric(0.1),
    operating_margin: metric(0.2),
    ocf_margin: metric(0.05),
    net_cash: metric(400),
    cash_runway_quarters: metric(null, ["operating_cash_flow_positive"]),
    rnd_intensity: metric(0.1),
    active_trials: null,
    phase_3_trials: null,
    pipeline_depth_score: null,
    pipeline_concentration: null,
    clinical_momentum: null,
    data_quality_flags: [],
    ...overrides,
  };
}

describe("cellOf", () => {
  it("prints numbers exactly, without rounding or separators", () => {
    expect(cellOf(row({ revenue_ttm: 63696000000 }), "revenue_ttm").text).toBe("63696000000");
    expect(cellOf(row({ revenue_ttm: -0.002146225306659565 }), "revenue_ttm").text).toBe(
      "-0.002146225306659565",
    );
  });

  it("distinguishes n/m from null", () => {
    const nm = cellOf(row({ revenue_growth_yoy: metric(null, ["not_meaningful_small_base"]) }), "revenue_growth_yoy");
    const nul = cellOf(row({ revenue_growth_yoy: metric(null, ["incomplete_window"]) }), "revenue_growth_yoy");

    expect(nm.text).toBe("n/m");
    expect(nm.state).toBe("not-meaningful");
    expect(nul.text).toBe("null");
    expect(nul.state).toBe("null");
  });

  it("never renders a missing value as zero or a dash", () => {
    const cell = cellOf(row({ revenue_ttm: null }), "revenue_ttm");
    expect(cell.text).toBe("null");
    expect(cell.text).not.toBe("0");
    expect(cell.text).not.toBe("—");
  });
});

describe("sorting", () => {
  const withGrowth = (ticker: string, m: MetricResult) =>
    row({ ticker, revenue_growth_yoy: m });

  const rows = [
    withGrowth("HIGH", metric(15.0)),
    withGrowth("NM", metric(null, ["not_meaningful_small_base"])),
    withGrowth("LOW", metric(-0.5)),
    withGrowth("NULL", metric(null, ["restated_fiscal_year"])),
    withGrowth("MID", metric(0.05)),
  ];

  it("sorts n/m and null to the end descending", () => {
    const sorted = [...rows].sort((a, b) => compareRows(a, b, "revenue_growth_yoy", "desc"));
    expect(sorted.map((r) => r.ticker)).toEqual(["HIGH", "MID", "LOW", "NM", "NULL"]);
  });

  it("sorts n/m and null to the end ascending too", () => {
    const sorted = [...rows].sort((a, b) => compareRows(a, b, "revenue_growth_yoy", "asc"));
    expect(sorted.map((r) => r.ticker)).toEqual(["LOW", "MID", "HIGH", "NM", "NULL"]);
  });

  it("never treats n/m as zero", () => {
    const sorted = [...rows].sort((a, b) => compareRows(a, b, "revenue_growth_yoy", "asc"));
    const nmIndex = sorted.findIndex((r) => r.ticker === "NM");
    const midIndex = sorted.findIndex((r) => r.ticker === "MID");
    // Zero would sort between LOW (-0.5) and MID (0.05).
    expect(nmIndex).toBeGreaterThan(midIndex);
  });

  it("never treats n/m as infinity", () => {
    const sorted = [...rows].sort((a, b) => compareRows(a, b, "revenue_growth_yoy", "desc"));
    expect(sorted[0].ticker).toBe("HIGH");
  });

  it("breaks ties on ticker so the order is stable", () => {
    const tied = [row({ ticker: "ZZZ" }), row({ ticker: "AAA" })];
    const sorted = [...tied].sort((a, b) => compareRows(a, b, "revenue_ttm", "desc"));
    expect(sorted.map((r) => r.ticker)).toEqual(["AAA", "ZZZ"]);
  });
});

describe("filters", () => {
  const universe = [
    row({ ticker: "BIG", subsector: "large_cap_pharma", revenue_ttm: 60e9, operating_margin: metric(0.25) }),
    row({
      ticker: "SMALL",
      subsector: "vaccines_infectious_disease",
      therapeutic_focus: ["vaccines"],
      revenue_ttm: 50e6,
      operating_margin: metric(-0.9),
      cash_runway_quarters: metric(3),
    }),
    row({
      ticker: "UNKNOWN",
      subsector: "medtech",
      therapeutic_focus: ["diagnostics"],
      revenue_ttm: null,
      operating_margin: metric(null, ["incomplete_window"]),
      operating_income_ttm: null,
    }),
  ];

  it("filters by subsector", () => {
    const out = applyFilters(universe, { ...DEFAULT_STATE.filters, subsectors: ["medtech"] });
    expect(out.map((r) => r.ticker)).toEqual(["UNKNOWN"]);
  });

  it("filters by therapeutic focus", () => {
    const out = applyFilters(universe, { ...DEFAULT_STATE.filters, focus: ["vaccines"] });
    expect(out.map((r) => r.ticker)).toEqual(["BIG", "SMALL"]);
  });

  it("excludes companies with no operating income from both profitability buckets", () => {
    const profitable = applyFilters(universe, { ...DEFAULT_STATE.filters, profitability: "profitable" });
    const unprofitable = applyFilters(universe, { ...DEFAULT_STATE.filters, profitability: "unprofitable" });

    expect(profitable.map((r) => r.ticker)).toEqual(["BIG"]);
    expect(unprofitable.map((r) => r.ticker)).toEqual(["SMALL"]);
    // UNKNOWN is assumed to be neither, rather than assumed lossmaking.
    expect([...profitable, ...unprofitable].map((r) => r.ticker)).not.toContain("UNKNOWN");
  });

  it("filters by runway band", () => {
    const out = applyFilters(universe, { ...DEFAULT_STATE.filters, runwayBands: ["lt4"] });
    expect(out.map((r) => r.ticker)).toEqual(["SMALL"]);
  });

  it("offers a band for companies with no runway figure", () => {
    const out = applyFilters(universe, { ...DEFAULT_STATE.filters, runwayBands: ["none"] });
    expect(out.map((r) => r.ticker)).toEqual(["BIG", "UNKNOWN"]);
    expect(RUNWAY_BANDS.map((b) => b.id)).toContain("none");
  });

  it("filters by revenue band", () => {
    const out = applyFilters(universe, { ...DEFAULT_STATE.filters, revenueBands: ["gte10b"] });
    expect(out.map((r) => r.ticker)).toEqual(["BIG"]);
  });

  it("combines filters conjunctively and can return nothing", () => {
    const out = applyFilters(universe, {
      ...DEFAULT_STATE.filters,
      subsectors: ["medtech"],
      revenueBands: ["gte10b"],
    });
    expect(out).toEqual([]);
  });
});

describe("url state", () => {
  it("round-trips a full screen", () => {
    const state = {
      filters: {
        subsectors: ["medtech", "payer"],
        focus: ["vaccines"],
        profitability: "unprofitable" as const,
        runwayBands: ["lt4"],
        revenueBands: ["gte10b"],
      },
      sortKey: "cash_runway_quarters",
      sortDir: "asc" as const,
      preset: "cash",
    };
    expect(decodeState(encodeState(state))).toEqual(state);
  });

  it("produces an empty query for the default screen", () => {
    expect(encodeState(DEFAULT_STATE)).toBe("");
  });

  it("falls back to defaults on nonsense input", () => {
    const state = decodeState("?profit=banana&dir=sideways&sort=");
    expect(state.filters.profitability).toBe("any");
    expect(state.sortDir).toBe("desc");
    expect(state.sortKey).toBe(DEFAULT_STATE.sortKey);
  });

  it("survives an empty query string", () => {
    expect(decodeState("")).toEqual(DEFAULT_STATE);
  });
});

describe("csv export", () => {
  const columns = [
    { key: "name", label: "Name" },
    { key: "revenue_ttm", label: "Revenue TTM" },
    { key: "revenue_growth_yoy", label: "Revenue growth YoY" },
  ];

  it("carries the as-of date and a flags column", () => {
    const csv = toCsv([row({ data_quality_flags: ["revenue:fallback_tag"] })], columns, "2026-09-07T01:00:00Z");
    const lines = csv.trim().split("\n");

    expect(lines[0]).toContain("2026-09-07T01:00:00Z");
    expect(lines[2]).toBe("Name,Revenue TTM,Revenue growth YoY,flags");
    expect(lines[3]).toContain("revenue:fallback_tag");
  });

  it("exports values exactly as displayed, including n/m and null", () => {
    const csv = toCsv(
      [
        row({ ticker: "A", revenue_growth_yoy: metric(null, ["not_meaningful_small_base"]) }),
        row({ ticker: "B", revenue_ttm: null, revenue_growth_yoy: metric(0.25) }),
      ],
      columns,
      "2026-09-07T01:00:00Z",
    );

    expect(csv).toContain("n/m");
    expect(csv).toContain("null");
    expect(csv).toContain("0.25");
  });

  it("quotes fields containing commas", () => {
    const csv = toCsv([row({ name: "Alpha, Inc." })], columns, "now");
    expect(csv).toContain('"Alpha, Inc."');
  });
});
