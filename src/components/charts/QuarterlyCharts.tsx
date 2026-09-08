/**
 * Company-page charts (SPEC §8). Recharts inside the existing React island.
 *
 * Three rules govern every chart here.
 *
 * **A null is a gap, never a zero.** Recharts bridges `null` by default;
 * `connectNulls={false}` plus a genuine `null` in the datum leaves the hole
 * visible. Becton Dickinson's Q2 FY2026 operating cash flow is missing because
 * deriving it would have meant subtracting one XBRL tag from another, and a line
 * drawn straight through that gap would assert a figure nobody filed.
 *
 * **A basis change is drawn, not just footnoted.** Where a series stops
 * measuring one thing and starts measuring another, the step at that point is a
 * change of definition rather than of the business. The cutover gets a vertical
 * rule and the segments either side are drawn differently. Where the change
 * happened before the visible window, a banner says so instead — the reader
 * still needs to know which basis they are looking at.
 *
 * **Axes are scaled, values are not.** Plotting raw dollars makes an axis
 * unreadable, so the axis is in millions and says so. Every tooltip shows the
 * exact figure the pipeline produced, and the tables below the charts remain the
 * unrounded record.
 */
import { useId, useMemo, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { basisLabel, describeFlag, type QualityRecord } from "../../lib/flags";

const MILLION = 1_000_000;

// SPEC §9. --advance and --retreat carry direction of change and nothing else,
// so neither is used as a series colour.
const INK = "#16222E";
const INK_MUTED = "#5A6B7A";
const RULE = "#D3DAE0";
const FIELD = "#EEF1F3";
const RETREAT = "#9B2C2C";

interface QuarterRow {
  period_end: string;
  revenue: number | null;
  rnd: number | null;
  ocf: number | null;
  cash: number | null;
  measurement_basis: Record<string, string | null>;
  flags: string[];
}

interface Cutover {
  from_basis: string;
  to_basis: string;
  last_period_end_before: string;
  first_period_end_after: string;
}

interface ConceptMeta {
  basis_cutovers: Cutover[];
  measurement_bases: string[];
}

interface Props {
  ticker: string;
  quarters: QuarterRow[];
  concepts: Record<string, ConceptMeta>;
  asOf: string;
  byPhase: Record<string, number> | null;
  phasesApplicable: boolean;
  pipelineAsOf: string | null;
}

/** Exact figure, for tooltips and text alternatives. Never rounded. */
function exact(value: number | null): string {
  return value === null || value === undefined ? "null" : String(value);
}

function millions(value: number | null): number | null {
  return value === null || value === undefined ? null : value / MILLION;
}

/** Axis ticks only. One decimal is plenty at this scale and never implies precision. */
function tick(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function flagsFor(row: QuarterRow, concept: string): string[] {
  return row.flags.filter((f) => f.startsWith(`${concept}:`));
}

function explain(flag: string): string {
  const [concept, code] = flag.includes(":") ? flag.split(":") : ["", flag];
  const record: QualityRecord = {
    code,
    concept,
    period_start: null,
    period_end: null,
    detail: {},
  };
  return describeFlag(record);
}

/**
 * Cutovers landing inside the visible window, and the basis prevailing across it.
 *
 * Both matter. Gilead's R&D basis changed in 2020 and Vertex's in 2022, which is
 * outside a twelve-quarter window for either — so those charts have no rule to
 * draw but still need to say which basis they are on, or a reader compares them
 * against a chart drawn on the other one.
 */
function basisContext(concept: ConceptMeta | undefined, window: string[]) {
  if (!concept) return { inWindow: [] as Cutover[], prevailing: [] as string[] };
  const visible = new Set(window);
  return {
    inWindow: concept.basis_cutovers.filter((c) => visible.has(c.first_period_end_after)),
    prevailing: concept.measurement_bases,
  };
}

function BasisNotice({
  label,
  concept,
  window,
  rows,
  conceptKey,
}: {
  label: string;
  concept: ConceptMeta | undefined;
  window: string[];
  rows: QuarterRow[];
  conceptKey: string;
}) {
  const { inWindow } = basisContext(concept, window);
  const shown = new Set(
    rows.map((r) => r.measurement_basis?.[conceptKey]).filter(Boolean) as string[],
  );
  const hadEarlierChange = (concept?.basis_cutovers.length ?? 0) > inWindow.length;

  if (inWindow.length === 0 && !hadEarlierChange) return null;

  return (
    <p className="chart-basis">
      {inWindow.length > 0 && (
        <>
          <strong>{label} changes basis inside this window.</strong>{" "}
          {inWindow
            .map(
              (c) =>
                `${basisLabel(c.from_basis)} up to ${c.last_period_end_before}, then ${basisLabel(
                  c.to_basis,
                )} from ${c.first_period_end_after}`,
            )
            .join("; ")}
          . The step at the marked line is a change of definition, not of the business.{" "}
        </>
      )}
      {inWindow.length === 0 && hadEarlierChange && (
        <>
          <strong>
            {label} is on the {[...shown].map(basisLabel).join(" and ")} basis throughout this
            window.
          </strong>{" "}
          The basis changed earlier in the series — before the twelve quarters shown — so figures
          from before then are not comparable with these.
        </>
      )}
    </p>
  );
}

function ChartTooltip({ active, payload, label, rows }: any) {
  if (!active || !payload?.length) return null;
  const row: QuarterRow | undefined = rows.find((r: QuarterRow) => r.period_end === label);
  return (
    <div className="chart-tip">
      <strong>{label}</strong>
      {payload.map((p: any) => (
        <div key={p.dataKey}>
          {p.name}: <span className="tabular">{exact(p.payload[`${p.dataKey}_exact`])}</span> USD
        </div>
      ))}
      {row && row.flags.length > 0 && (
        <div className="chart-tip-flags">{row.flags.map(explain).join(" ")}</div>
      )}
    </div>
  );
}

/** A point drawn differently when the underlying value carries a flag. */
function FlaggedDot(props: any) {
  const { cx, cy, payload, dataKey, stroke } = props;
  if (cx === undefined || cy === undefined || payload[dataKey] === null) return null;
  const flagged: boolean = payload[`${dataKey.replace("_m", "")}_flagged`];
  return flagged ? (
    <g>
      <circle cx={cx} cy={cy} r={5} fill={RETREAT} stroke="#fff" strokeWidth={1} />
      <circle cx={cx} cy={cy} r={9} fill="none" stroke={RETREAT} strokeWidth={1} opacity={0.5} />
    </g>
  ) : (
    <circle cx={cx} cy={cy} r={2.5} fill={stroke} />
  );
}

export default function QuarterlyCharts({
  ticker,
  quarters,
  concepts,
  asOf,
  byPhase,
  phasesApplicable,
  pipelineAsOf,
}: Props) {
  const [showTable, setShowTable] = useState(false);
  const window = quarters.map((q) => q.period_end);

  const data = useMemo(
    () =>
      quarters.map((q) => ({
        period_end: q.period_end,
        revenue_m: millions(q.revenue),
        rnd_m: millions(q.rnd),
        cash_m: millions(q.cash),
        ocf_m: millions(q.ocf),
        revenue_exact: q.revenue,
        rnd_exact: q.rnd,
        cash_exact: q.cash,
        ocf_exact: q.ocf,
        revenue_flagged: flagsFor(q, "revenue").length > 0,
        rnd_flagged: flagsFor(q, "rnd").length > 0,
        cash_flagged: flagsFor(q, "cash").length > 0,
        ocf_flagged: flagsFor(q, "ocf").length > 0,
      })),
    [quarters],
  );

  const revenueCuts = basisContext(concepts.revenue, window).inWindow;
  const rndCuts = basisContext(concepts.rnd, window).inWindow;
  const ocfCuts = basisContext(concepts.ocf, window).inWindow;
  const cashCuts = basisContext(concepts.cash, window).inWindow;

  const phaseData = useMemo(() => {
    if (!byPhase) return [];
    return [
      ["Phase 1", byPhase.phase_1 ?? 0],
      ["Phase 2", byPhase.phase_2 ?? 0],
      ["Phase 3", byPhase.phase_3 ?? 0],
      ["Phase 4", byPhase.phase_4 ?? 0],
      ["No phase", byPhase.not_applicable ?? 0],
    ].map(([phase, count]) => ({ phase, count }));
  }, [byPhase]);

  const gridId = useId();

  return (
    <div className="charts">
      <p className="chart-note">
        Charts are drawn from the same figures as the tables below, which remain the exact record.
        Axes are in millions of US dollars and labelled as such; every tooltip carries the exact
        unrounded figure. A missing quarter is drawn as a gap, never bridged or zeroed. Points
        carrying a data-quality flag are ringed in red.{" "}
        <button className="link" onClick={() => setShowTable((v) => !v)} aria-expanded={showTable}>
          {showTable ? "Hide" : "Show"} the chart data as text
        </button>
      </p>

      {/* ---------------------------------------------------------------- */}
      <h3 id={`${gridId}-rev`}>Revenue and R&D by quarter</h3>
      <p className="chart-asof">Last {quarters.length} quarters. Data as of {asOf}.</p>
      <BasisNotice label="Revenue" concept={concepts.revenue} window={window} rows={quarters} conceptKey="revenue" />
      <BasisNotice label="R&D expense" concept={concepts.rnd} window={window} rows={quarters} conceptKey="rnd" />

      <div className="chart-frame">
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid stroke={RULE} strokeDasharray="2 3" vertical={false} />
            <XAxis dataKey="period_end" tick={{ fontSize: 11, fill: INK_MUTED }} stroke={RULE} />
            <YAxis
              tick={{ fontSize: 11, fill: INK_MUTED }}
              stroke={RULE}
              tickFormatter={tick}
              label={{
                value: "USD millions ($M)",
                angle: -90,
                position: "insideLeft",
                style: { fontSize: 11, fill: INK_MUTED },
              }}
            />
            <Tooltip content={<ChartTooltip rows={quarters} />} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {[...revenueCuts, ...rndCuts].map((c) => (
              <ReferenceLine
                key={`${c.from_basis}-${c.first_period_end_after}`}
                x={c.first_period_end_after}
                stroke={INK}
                strokeDasharray="4 3"
                label={{ value: "basis change", position: "top", style: { fontSize: 10, fill: INK } }}
              />
            ))}
            <Line
              type="linear"
              dataKey="revenue_m"
              name="Revenue"
              stroke={INK}
              strokeWidth={2}
              connectNulls={false}
              dot={<FlaggedDot />}
              isAnimationActive={false}
            />
            <Line
              type="linear"
              dataKey="rnd_m"
              name="R&D expense"
              stroke={INK_MUTED}
              strokeWidth={2}
              strokeDasharray="5 3"
              connectNulls={false}
              dot={<FlaggedDot />}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* ---------------------------------------------------------------- */}
      <h3>Cash and operating cash flow by quarter</h3>
      <p className="chart-asof">
        Last {quarters.length} quarters. Cash is a balance at the quarter end; operating cash flow
        is the flow across the quarter, on the right axis. Data as of {asOf}.
      </p>
      <BasisNotice label="Cash" concept={concepts.cash} window={window} rows={quarters} conceptKey="cash" />
      <BasisNotice label="Operating cash flow" concept={concepts.ocf} window={window} rows={quarters} conceptKey="ocf" />

      <div className="chart-frame">
        <ResponsiveContainer width="100%" height={280}>
          <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid stroke={RULE} strokeDasharray="2 3" vertical={false} />
            <XAxis dataKey="period_end" tick={{ fontSize: 11, fill: INK_MUTED }} stroke={RULE} />
            <YAxis
              yAxisId="cash"
              tick={{ fontSize: 11, fill: INK_MUTED }}
              stroke={RULE}
              tickFormatter={tick}
              label={{
                value: "Cash, USD millions ($M)",
                angle: -90,
                position: "insideLeft",
                style: { fontSize: 11, fill: INK_MUTED },
              }}
            />
            <YAxis
              yAxisId="ocf"
              orientation="right"
              tick={{ fontSize: 11, fill: INK_MUTED }}
              stroke={RULE}
              tickFormatter={tick}
              label={{
                value: "Operating cash flow, USD millions ($M)",
                angle: 90,
                position: "insideRight",
                style: { fontSize: 11, fill: INK_MUTED },
              }}
            />
            <Tooltip content={<ChartTooltip rows={quarters} />} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <ReferenceLine yAxisId="ocf" y={0} stroke={INK_MUTED} strokeWidth={1} />
            {[...cashCuts, ...ocfCuts].map((c) => (
              <ReferenceLine
                key={`${c.from_basis}-${c.first_period_end_after}`}
                yAxisId="cash"
                x={c.first_period_end_after}
                stroke={INK}
                strokeDasharray="4 3"
                label={{ value: "basis change", position: "top", style: { fontSize: 10, fill: INK } }}
              />
            ))}
            <Bar yAxisId="cash" dataKey="cash_m" name="Cash" fill={FIELD} stroke={INK_MUTED} isAnimationActive={false} />
            <Line
              yAxisId="ocf"
              type="linear"
              dataKey="ocf_m"
              name="Operating cash flow"
              stroke={INK}
              strokeWidth={2}
              connectNulls={false}
              dot={<FlaggedDot />}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* ---------------------------------------------------------------- */}
      {phasesApplicable && phaseData.length > 0 && (
        <>
          <h3>Active trials by phase</h3>
          <p className="chart-asof">
            Interventional studies led by this company. A trial declaring several phases counts once,
            at its highest. Registry as of {pipelineAsOf ?? asOf}.
          </p>
          <div className="chart-frame">
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart
                data={phaseData}
                layout="vertical"
                margin={{ top: 8, right: 24, bottom: 8, left: 24 }}
              >
                <CartesianGrid stroke={RULE} strokeDasharray="2 3" horizontal={false} />
                <XAxis
                  type="number"
                  allowDecimals={false}
                  tick={{ fontSize: 11, fill: INK_MUTED }}
                  stroke={RULE}
                  label={{
                    value: "Active trials",
                    position: "insideBottom",
                    offset: -4,
                    style: { fontSize: 11, fill: INK_MUTED },
                  }}
                />
                <YAxis
                  type="category"
                  dataKey="phase"
                  width={80}
                  tick={{ fontSize: 11, fill: INK }}
                  stroke={RULE}
                />
                <Tooltip
                  formatter={(v: any) => [`${v} active trials`, ""]}
                  contentStyle={{ fontSize: 12 }}
                />
                <Bar dataKey="count" fill={INK} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      {/* Text alternative: the same information, reachable without the charts. */}
      <div className={showTable ? "chart-alt" : "visually-hidden"}>
        <h4>Chart data as text</h4>
        <table>
          <caption>
            {ticker} quarterly figures behind the charts above, exactly as filed. Data as of {asOf}.
          </caption>
          <thead>
            <tr>
              <th>Quarter end</th>
              <th className="num">Revenue</th>
              <th className="num">R&D</th>
              <th className="num">Cash</th>
              <th className="num">Operating cash flow</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {quarters.map((q) => (
              <tr key={q.period_end}>
                <td>{q.period_end}</td>
                <td className={`num ${q.revenue === null ? "null" : ""}`}>{exact(q.revenue)}</td>
                <td className={`num ${q.rnd === null ? "null" : ""}`}>{exact(q.rnd)}</td>
                <td className={`num ${q.cash === null ? "null" : ""}`}>{exact(q.cash)}</td>
                <td className={`num ${q.ocf === null ? "null" : ""}`}>{exact(q.ocf)}</td>
                <td className="muted">
                  {q.flags.length ? q.flags.map((f) => <span key={f} tabIndex={0} title={explain(f)}>{f} </span>) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {phasesApplicable && byPhase && (
          <table>
            <caption>Active trials by phase, as of {pipelineAsOf ?? asOf}.</caption>
            <thead>
              <tr><th>Phase</th><th className="num">Active trials</th></tr>
            </thead>
            <tbody>
              {phaseData.map((p) => (
                <tr key={p.phase}>
                  <td>{p.phase}</td>
                  <td className="num">{p.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
