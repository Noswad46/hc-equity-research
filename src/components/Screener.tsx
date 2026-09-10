/**
 * The screener table (SPEC §8).
 *
 * Everything runs client-side over JSON loaded with the page — no network calls
 * at runtime, no server. Figures are printed exactly as the pipeline emitted
 * them; the only presentational decision this component makes about a number is
 * whether it is a number, `n/m`, or `null`, and those three never collapse into
 * one another.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DEFAULT_STATE,
  REVENUE_BANDS,
  RUNWAY_BANDS,
  applyFilters,
  cellOf,
  compareRows,
  decodeState,
  encodeState,
  toCsv,
  type CompanyRow,
  type Filters,
  type Profitability,
  type ScreenState,
} from "../lib/screener";
import { describeFlag, describeReason, describeStale, conceptLabel } from "../lib/flags";

interface Column {
  key: string;
  label: string;
  numeric: boolean;
  /** Units, so a raw unrounded figure is at least interpretable. */
  note?: string;
}

const IDENTITY: Column[] = [
  { key: "name", label: "Name", numeric: false },
  { key: "subsector", label: "Subsector", numeric: false },
];

const PRESETS: { id: string; label: string; columns: Column[] }[] = [
  {
    id: "fundamentals",
    label: "Fundamentals",
    columns: [
      ...IDENTITY,
      { key: "fiscal_period_end", label: "Period end", numeric: false },
      { key: "revenue_ttm", label: "Revenue TTM", numeric: true, note: "USD" },
      { key: "revenue_growth_yoy", label: "Revenue growth YoY", numeric: true, note: "fraction" },
      { key: "rnd_ttm", label: "R&D TTM", numeric: true, note: "USD" },
      { key: "rnd_intensity", label: "R&D intensity", numeric: true, note: "fraction" },
      // OCF and net margin lead: both are universally tagged. Operating margin
      // follows, blank for the filers that present no such subtotal.
      { key: "ocf_margin", label: "OCF margin", numeric: true, note: "fraction" },
      { key: "net_margin", label: "Net margin", numeric: true, note: "fraction" },
      { key: "operating_margin", label: "Operating margin", numeric: true, note: "fraction" },
    ],
  },
  {
    id: "cash",
    label: "Cash & burn",
    columns: [
      ...IDENTITY,
      { key: "cash", label: "Cash", numeric: true, note: "USD" },
      { key: "net_cash", label: "Net cash", numeric: true, note: "USD" },
      { key: "ocf_ttm", label: "OCF TTM", numeric: true, note: "USD" },
      { key: "cash_runway_quarters", label: "Runway", numeric: true, note: "quarters" },
      { key: "rnd_ttm", label: "R&D TTM", numeric: true, note: "USD" },
    ],
  },
  {
    id: "pipeline",
    label: "Pipeline",
    columns: [
      ...IDENTITY,
      { key: "active_trials", label: "Active trials", numeric: true },
      { key: "phase_3_trials", label: "Phase 3", numeric: true },
      { key: "pipeline_depth_score", label: "Depth score", numeric: true, note: "weighted" },
      { key: "pipeline_concentration", label: "Concentration", numeric: true, note: "HHI" },
      { key: "clinical_momentum", label: "Momentum", numeric: true, note: "trials" },
      { key: "discontinuation_rate", label: "Discontinuation", numeric: true, note: "fraction" },
      // R&D per late-stage programme is deliberately not here. Trial count is a
      // weak proxy for programme count: one Phase 3 run across four indications
      // registers as four trials, while a basket trial across four registers as
      // one. The denominator tracks registry practice rather than R&D
      // allocation, so the metric is defensible within a subsector and not
      // across one. It stays on the company page, where that context is present.
    ],
  },
];

interface Props {
  companies: CompanyRow[];
  generatedAt: string;
  growthFloor: number;
}

function unique(values: string[]): string[] {
  return [...new Set(values)].sort();
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export default function Screener({ companies, generatedAt, growthFloor }: Props) {
  const [state, setState] = useState<ScreenState>(DEFAULT_STATE);
  const [hydrated, setHydrated] = useState(false);
  const liveRef = useRef<HTMLParagraphElement>(null);

  // Restore from the URL once mounted, so a shared link opens the same screen.
  useEffect(() => {
    setState(decodeState(window.location.search));
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    const query = encodeState(state);
    const url = query ? `${window.location.pathname}?${query}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  }, [state, hydrated]);

  const preset = PRESETS.find((p) => p.id === state.preset) ?? PRESETS[0];
  const columns = preset.columns;

  const subsectors = useMemo(() => unique(companies.map((c) => c.subsector)), [companies]);
  const focuses = useMemo(
    () => unique(companies.flatMap((c) => c.therapeutic_focus)),
    [companies],
  );

  const rows = useMemo(() => {
    const filtered = applyFilters(companies, state.filters);
    const key = state.sortKey;
    return [...filtered].sort((a, b) => {
      if (key === "name" || key === "subsector" || key === "ticker" || key === "fiscal_period_end") {
        const av = String((a as any)[key] ?? "");
        const bv = String((b as any)[key] ?? "");
        const cmp = av.localeCompare(bv);
        return state.sortDir === "asc" ? cmp : -cmp;
      }
      return compareRows(a, b, key, state.sortDir);
    });
  }, [companies, state]);

  const staleRows = useMemo(() => rows.filter((r) => r.stale), [rows]);

  useEffect(() => {
    if (liveRef.current) liveRef.current.textContent = `${rows.length} of ${companies.length} companies match.`;
  }, [rows.length, companies.length]);

  const setFilters = useCallback((update: Partial<Filters>) => {
    setState((s) => ({ ...s, filters: { ...s.filters, ...update } }));
  }, []);

  const sortBy = useCallback((key: string) => {
    setState((s) =>
      s.sortKey === key
        ? { ...s, sortDir: s.sortDir === "asc" ? "desc" : "asc" }
        : { ...s, sortKey: key, sortDir: "desc" },
    );
  }, []);

  const exportCsv = useCallback(() => {
    const csv = toCsv(rows, columns, generatedAt);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `screener-${preset.id}-${generatedAt.slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [rows, columns, generatedAt, preset.id]);

  const activeFilters =
    state.filters.subsectors.length +
    state.filters.focus.length +
    state.filters.runwayBands.length +
    state.filters.revenueBands.length +
    (state.filters.profitability !== "any" ? 1 : 0);

  return (
    <div className="screener">
      <div className="controls">
        <fieldset>
          <legend>Subsector</legend>
          <div className="options">
            {subsectors.map((value) => (
              <label key={value}>
                <input
                  type="checkbox"
                  checked={state.filters.subsectors.includes(value)}
                  onChange={() => setFilters({ subsectors: toggle(state.filters.subsectors, value) })}
                />
                {value}
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend>Therapeutic focus</legend>
          <div className="options">
            {focuses.map((value) => (
              <label key={value}>
                <input
                  type="checkbox"
                  checked={state.filters.focus.includes(value)}
                  onChange={() => setFilters({ focus: toggle(state.filters.focus, value) })}
                />
                {value}
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend>Profitability</legend>
          <div className="options">
            {(["any", "profitable", "unprofitable"] as Profitability[]).map((value) => (
              <label key={value}>
                <input
                  type="radio"
                  name="profitability"
                  checked={state.filters.profitability === value}
                  onChange={() => setFilters({ profitability: value })}
                />
                {value}
              </label>
            ))}
          </div>
          <p className="hint">
            Judged on trailing operating cash flow, falling back to net income. Companies with
            neither are in neither bucket.
          </p>
        </fieldset>

        <fieldset>
          <legend>Cash runway</legend>
          <div className="options">
            {RUNWAY_BANDS.map((band) => (
              <label key={band.id}>
                <input
                  type="checkbox"
                  checked={state.filters.runwayBands.includes(band.id)}
                  onChange={() => setFilters({ runwayBands: toggle(state.filters.runwayBands, band.id) })}
                />
                {band.label}
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend>Revenue TTM</legend>
          <div className="options">
            {REVENUE_BANDS.map((band) => (
              <label key={band.id}>
                <input
                  type="checkbox"
                  checked={state.filters.revenueBands.includes(band.id)}
                  onChange={() => setFilters({ revenueBands: toggle(state.filters.revenueBands, band.id) })}
                />
                {band.label}
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      <div className="toolbar">
        <div className="presets" role="tablist" aria-label="Column preset">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              role="tab"
              aria-selected={p.id === preset.id}
              className={p.id === preset.id ? "preset active" : "preset"}
              onClick={() => setState((s) => ({ ...s, preset: p.id }))}
            >
              {p.label}
            </button>
          ))}
        </div>

        <p className="count" aria-hidden="true">
          <strong>{rows.length}</strong> of {companies.length} companies
          {activeFilters > 0 ? ` · ${activeFilters} filter${activeFilters === 1 ? "" : "s"}` : ""}
        </p>
        <p ref={liveRef} className="visually-hidden" role="status" aria-live="polite" />

        <div className="actions">
          {activeFilters > 0 && (
            <button onClick={() => setState((s) => ({ ...s, filters: DEFAULT_STATE.filters }))}>
              Clear filters
            </button>
          )}
          <button onClick={exportCsv} disabled={rows.length === 0}>
            Export CSV
          </button>
        </div>
      </div>

      {preset.id === "pipeline" && (
        <p className="notice">
          Interventional studies where the company is the <strong>lead</strong> sponsor, counted
          from ClinicalTrials.gov by exact sponsor name. Weights and thresholds are on the{" "}
          <a href="/methodology/">methodology page</a>. Depth score is zero for companies whose
          trials carry no phase, which is normal for device studies.
        </p>
      )}

      {staleRows.length > 0 && (
        // Stated up front, not only in a tooltip. A reader scanning the table
        // should not have to hover a row to find out it is a refresh behind.
        <p className="notice">
          <strong>
            {staleRows.length} {staleRows.length === 1 ? "company" : "companies"}
          </strong>{" "}
          in this view show figures from an earlier run, marked{" "}
          <span aria-hidden="true">†</span>: their last refresh failed. Hover the ticker for the
          date the figures come from. A company is dropped from the universe rather than carried
          further once it has failed repeatedly, so nothing here is more than a few refreshes old.
        </p>
      )}

      {rows.length === 0 ? (
        <p className="empty">
          No companies match these filters. <button onClick={() => setState((s) => ({ ...s, filters: DEFAULT_STATE.filters }))}>Clear filters</button> to
          start again.
        </p>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="visually-hidden">
              Healthcare companies, filterable and sortable. Data as of {generatedAt}.
            </caption>
            <thead>
              <tr>
                <th scope="col" className="sticky-col">
                  <SortButton
                    label="Ticker"
                    active={state.sortKey === "ticker"}
                    dir={state.sortDir}
                    onClick={() => sortBy("ticker")}
                  />
                </th>
                {columns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className={column.numeric ? "num" : undefined}
                    aria-sort={
                      state.sortKey === column.key
                        ? state.sortDir === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                    }
                  >
                    <SortButton
                      label={column.label}
                      note={column.note}
                      active={state.sortKey === column.key}
                      dir={state.sortDir}
                      onClick={() => sortBy(column.key)}
                    />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.ticker}>
                  <th scope="row" className="sticky-col">
                    <a href={`/companies/${row.ticker}/`}>{row.ticker}</a>
                    {row.stale && (
                      // Marked on the ticker rather than on each cell: the whole
                      // row is one refresh behind, and repeating the mark across
                      // nine columns would say the same thing nine times.
                      <span className="stale" tabIndex={0} title={describeStale(row.stale)}>
                        <span aria-hidden="true">†</span>
                        <span className="visually-hidden"> — {describeStale(row.stale)}</span>
                      </span>
                    )}
                  </th>
                  {columns.map((column) => (
                    <Cell key={column.key} row={row} column={column} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="hint">
        Figures are printed exactly as filed with the SEC — unrounded and unscaled.{" "}
        <strong>null</strong> means the pipeline produced no value, which is not zero.{" "}
        <strong>n/m</strong> means not meaningful: growth is suppressed where the prior trailing
        year was below {growthFloor} USD, because a percentage off a near-zero base describes the
        base rather than the business. Both sort to the end of a column in either direction.
      </p>
    </div>
  );
}

function SortButton({
  label,
  note,
  active,
  dir,
  onClick,
}: {
  label: string;
  note?: string;
  active: boolean;
  dir: "asc" | "desc";
  onClick: () => void;
}) {
  return (
    <button className={active ? "sort active" : "sort"} onClick={onClick}>
      {label}
      {note && <span className="unit"> ({note})</span>}
      <span aria-hidden="true" className="arrow">
        {active ? (dir === "asc" ? "▲" : "▼") : ""}
      </span>
    </button>
  );
}

function Cell({ row, column }: { row: CompanyRow; column: Column }) {
  const cell = cellOf(row, column.key);


  // Flags attached to the metric's own inputs, plus any company-level flag for
  // the concept this column is built from.
  const conceptKey = column.key.split("_")[0];
  const related = row.data_quality_flags.filter((f) => f.startsWith(`${conceptKey}:`));
  const marks = [...cell.flags, ...related];

  const explanation = [
    ...cell.reasons.map((code) => describeReason(code, conceptLabel(conceptKey))),
    ...marks.map((code) =>
      describeFlag({
        code: code.includes(":") ? code.split(":")[1] : code,
        concept: code.includes(":") ? code.split(":")[0] : conceptKey,
        period_start: null,
        period_end: null,
        detail: {},
      }),
    ),
  ].join(" ");

  const flagged = marks.length > 0 || cell.state !== "value";

  return (
    <td className={[column.numeric ? "num" : "", cell.state === "value" ? "" : "null"].join(" ").trim()}>
      {flagged && explanation ? (
        <span className="flagged" tabIndex={0} title={explanation}>
          {cell.text}
          <span aria-hidden="true" className="marker">
            *
          </span>
          <span className="visually-hidden"> — {explanation}</span>
        </span>
      ) : (
        cell.text
      )}
    </td>
  );
}
