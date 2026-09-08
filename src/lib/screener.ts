/**
 * Shared types and pure helpers for the screener island.
 *
 * Nothing here formats a figure. Values are printed exactly as the pipeline
 * produced them, and the only transformation applied anywhere is choosing
 * between a number, the word `null`, and `n/m` — three distinct states that must
 * never collapse into each other.
 */

/** A SPEC §6 metric as `run.py` emits it: a value, or the reason there isn't one. */
export interface MetricResult {
  name: string;
  value: number | null;
  suppressed: boolean;
  suppressed_by: string[];
  flags: string[];
  period_ends: string[];
}

export interface CompanyRow {
  ticker: string;
  cik: string;
  name: string;
  subsector: string;
  therapeutic_focus: string[];
  fiscal_period_end: string | null;
  revenue_ttm: number | null;
  rnd_ttm: number | null;
  ocf_ttm: number | null;
  operating_income_ttm: number | null;
  net_income_ttm: number | null;
  cash: number | null;
  revenue_growth_yoy: MetricResult | null;
  operating_margin: MetricResult | null;
  ocf_margin: MetricResult | null;
  net_margin: MetricResult | null;
  net_cash: MetricResult | null;
  cash_runway_quarters: MetricResult | null;
  rnd_intensity: MetricResult | null;
  active_trials: number | null;
  phase_3_trials: number | null;
  pipeline_depth_score: MetricResult | null;
  pipeline_concentration: MetricResult | null;
  clinical_momentum: MetricResult | null;
  discontinuation_rate: MetricResult | null;
  rnd_per_late_stage_programme: MetricResult | null;
  data_quality_flags: string[];
}

/** The reason code that means "arithmetically true, but not worth reporting". */
export const NOT_MEANINGFUL = "not_meaningful_small_base";

export type CellState = "value" | "not-meaningful" | "null";

export interface Cell {
  state: CellState;
  /** Exactly what to print. Never rounded, never separated, never a dash. */
  text: string;
  value: number | null;
  flags: string[];
  reasons: string[];
}

function isMetric(value: unknown): value is MetricResult {
  return typeof value === "object" && value !== null && "suppressed_by" in value;
}

/** Read any screener field into a printable cell. */
export function cellOf(row: CompanyRow, key: string): Cell {
  const raw = (row as any)[key];

  if (isMetric(raw)) {
    if (raw.value !== null) {
      return { state: "value", text: String(raw.value), value: raw.value, flags: raw.flags, reasons: [] };
    }
    const notMeaningful = raw.suppressed_by.includes(NOT_MEANINGFUL);
    return {
      state: notMeaningful ? "not-meaningful" : "null",
      text: notMeaningful ? "n/m" : "null",
      value: null,
      flags: raw.flags,
      reasons: raw.suppressed_by,
    };
  }

  if (raw === null || raw === undefined) {
    return { state: "null", text: "null", value: null, flags: [], reasons: [] };
  }
  if (typeof raw === "number") {
    return { state: "value", text: String(raw), value: raw, flags: [], reasons: [] };
  }
  return { state: "value", text: String(raw), value: null, flags: [], reasons: [] };
}

/**
 * Sort comparator that keeps unsortable cells out of the way.
 *
 * `n/m` and `null` sort to the end in *both* directions. Treating them as zero
 * or infinity would put the names with the least meaningful data at the top of
 * a growth or runway screen, which is precisely the outcome the `n/m` rule
 * exists to prevent.
 */
export function compareRows(a: CompanyRow, b: CompanyRow, key: string, dir: "asc" | "desc"): number {
  const ca = cellOf(a, key);
  const cb = cellOf(b, key);

  const aMissing = ca.value === null;
  const bMissing = cb.value === null;
  if (aMissing && bMissing) return a.ticker.localeCompare(b.ticker);
  if (aMissing) return 1;
  if (bMissing) return -1;

  if (typeof ca.value === "number" && typeof cb.value === "number") {
    const delta = ca.value - cb.value;
    if (delta !== 0) return dir === "asc" ? delta : -delta;
    return a.ticker.localeCompare(b.ticker);
  }

  const cmp = ca.text.localeCompare(cb.text);
  if (cmp !== 0) return dir === "asc" ? cmp : -cmp;
  return a.ticker.localeCompare(b.ticker);
}

/** Text columns sort alphabetically and have no missing state. */
export function compareText(a: string, b: string, dir: "asc" | "desc"): number {
  const cmp = a.localeCompare(b);
  return dir === "asc" ? cmp : -cmp;
}

// --------------------------------------------------------------------------- //
// Filters
// --------------------------------------------------------------------------- //

export type Profitability = "any" | "profitable" | "unprofitable";

export interface Filters {
  subsectors: string[];
  focus: string[];
  profitability: Profitability;
  runwayBands: string[];
  revenueBands: string[];
}

export const EMPTY_FILTERS: Filters = {
  subsectors: [],
  focus: [],
  profitability: "any",
  runwayBands: [],
  revenueBands: [],
};

export interface Band {
  id: string;
  label: string;
  test: (row: CompanyRow) => boolean;
}

const runwayValue = (row: CompanyRow) => row.cash_runway_quarters?.value ?? null;

export const RUNWAY_BANDS: Band[] = [
  { id: "lt4", label: "Under 4 quarters", test: (r) => { const v = runwayValue(r); return v !== null && v < 4; } },
  { id: "4-8", label: "4 to 8 quarters", test: (r) => { const v = runwayValue(r); return v !== null && v >= 4 && v < 8; } },
  { id: "8-12", label: "8 to 12 quarters", test: (r) => { const v = runwayValue(r); return v !== null && v >= 8 && v < 12; } },
  { id: "gte12", label: "12 quarters or more", test: (r) => { const v = runwayValue(r); return v !== null && v >= 12; } },
  {
    id: "none",
    label: "No runway figure",
    // Cash generative, or suppressed. Deliberately selectable: "which names have
    // no runway number, and why" is a real question.
    test: (r) => runwayValue(r) === null,
  },
];

export const REVENUE_BANDS: Band[] = [
  { id: "lt100m", label: "Under $100m", test: (r) => r.revenue_ttm !== null && r.revenue_ttm < 100e6 },
  { id: "100m-1b", label: "$100m to $1bn", test: (r) => r.revenue_ttm !== null && r.revenue_ttm >= 100e6 && r.revenue_ttm < 1e9 },
  { id: "1b-10b", label: "$1bn to $10bn", test: (r) => r.revenue_ttm !== null && r.revenue_ttm >= 1e9 && r.revenue_ttm < 10e9 },
  { id: "gte10b", label: "$10bn or more", test: (r) => r.revenue_ttm !== null && r.revenue_ttm >= 10e9 },
  { id: "none", label: "No revenue figure", test: (r) => r.revenue_ttm === null },
];

/**
 * Profitability is judged on operating cash flow first, then net income.
 *
 * It used to key on operating income, which left Pfizer, Merck and J&J in
 * neither bucket — none of the three tags an operating income subtotal, so a
 * third of the universe vanished from a filter that is supposed to split it.
 * Cash generative versus cash burning is also the more meaningful division for
 * healthcare: it is what determines whether a company needs the capital markets.
 *
 * A company with neither figure is still in neither bucket, rather than assumed
 * lossmaking.
 */
function isProfitable(row: CompanyRow): boolean | null {
  if (row.ocf_ttm !== null) return row.ocf_ttm > 0;
  if (row.net_income_ttm !== null) return row.net_income_ttm > 0;
  const net = row.net_margin?.value ?? null;
  if (net !== null) return net > 0;
  return null;
}

export function applyFilters(rows: CompanyRow[], filters: Filters): CompanyRow[] {
  return rows.filter((row) => {
    if (filters.subsectors.length && !filters.subsectors.includes(row.subsector)) return false;
    if (filters.focus.length && !filters.focus.some((f) => row.therapeutic_focus.includes(f))) return false;

    if (filters.profitability !== "any") {
      const profitable = isProfitable(row);
      if (profitable === null) return false;
      if (filters.profitability === "profitable" && !profitable) return false;
      if (filters.profitability === "unprofitable" && profitable) return false;
    }

    if (filters.runwayBands.length) {
      const bands = RUNWAY_BANDS.filter((b) => filters.runwayBands.includes(b.id));
      if (!bands.some((b) => b.test(row))) return false;
    }
    if (filters.revenueBands.length) {
      const bands = REVENUE_BANDS.filter((b) => filters.revenueBands.includes(b.id));
      if (!bands.some((b) => b.test(row))) return false;
    }
    return true;
  });
}

// --------------------------------------------------------------------------- //
// URL state
// --------------------------------------------------------------------------- //

export interface ScreenState {
  filters: Filters;
  sortKey: string;
  sortDir: "asc" | "desc";
  preset: string;
}

export const DEFAULT_STATE: ScreenState = {
  filters: EMPTY_FILTERS,
  sortKey: "revenue_ttm",
  sortDir: "desc",
  preset: "fundamentals",
};

export function encodeState(state: ScreenState): string {
  const params = new URLSearchParams();
  const f = state.filters;
  if (f.subsectors.length) params.set("subsector", f.subsectors.join(","));
  if (f.focus.length) params.set("focus", f.focus.join(","));
  if (f.profitability !== "any") params.set("profit", f.profitability);
  if (f.runwayBands.length) params.set("runway", f.runwayBands.join(","));
  if (f.revenueBands.length) params.set("revenue", f.revenueBands.join(","));
  if (state.sortKey !== DEFAULT_STATE.sortKey) params.set("sort", state.sortKey);
  if (state.sortDir !== DEFAULT_STATE.sortDir) params.set("dir", state.sortDir);
  if (state.preset !== DEFAULT_STATE.preset) params.set("preset", state.preset);
  return params.toString();
}

export function decodeState(search: string): ScreenState {
  const params = new URLSearchParams(search);
  const list = (key: string) => {
    const raw = params.get(key);
    return raw ? raw.split(",").filter(Boolean) : [];
  };
  const profit = params.get("profit");
  return {
    filters: {
      subsectors: list("subsector"),
      focus: list("focus"),
      profitability:
        profit === "profitable" || profit === "unprofitable" ? profit : "any",
      runwayBands: list("runway"),
      revenueBands: list("revenue"),
    },
    sortKey: params.get("sort") || DEFAULT_STATE.sortKey,
    sortDir: params.get("dir") === "asc" ? "asc" : "desc",
    preset: params.get("preset") || DEFAULT_STATE.preset,
  };
}

// --------------------------------------------------------------------------- //
// CSV
// --------------------------------------------------------------------------- //

function csvField(text: string): string {
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/**
 * Export the current view, exactly as displayed.
 *
 * Carries the as-of date and a flags column, so an exported screen can still be
 * audited once it is out of the page and away from the tooltips.
 */
export function toCsv(
  rows: CompanyRow[],
  columns: { key: string; label: string }[],
  generatedAt: string,
): string {
  const lines: string[] = [];
  lines.push(`# Healthcare equity screener. Data as of ${generatedAt}.`);
  lines.push("# Figures are as filed with the SEC, unrounded. n/m = not meaningful. null = no value produced.");
  lines.push([...columns.map((c) => csvField(c.label)), "flags"].join(","));

  for (const row of rows) {
    const cells = columns.map((c) => csvField(cellOf(row, c.key).text));
    cells.push(csvField(row.data_quality_flags.join(" ")));
    lines.push(cells.join(","));
  }
  return lines.join("\n") + "\n";
}
