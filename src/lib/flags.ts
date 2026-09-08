/**
 * Turns the pipeline's flag codes into sentences a reader can act on.
 *
 * The wording lives here rather than in the JSON so there is one copy of it and
 * the data files stay free of prose. Every code the pipeline can emit must have
 * an entry; `describeFlag` falls back to the raw code rather than swallowing an
 * unknown one, because a flag nobody can read is worse than an ugly one.
 */

export interface QualityRecord {
  code: string;
  concept: string;
  period_start: string | null;
  period_end: string | null;
  detail?: Record<string, any> | null;
}

const CONCEPT_LABELS: Record<string, string> = {
  revenue: "Revenue",
  rnd: "R&D expense",
  ocf: "Operating cash flow",
  cash: "Cash",
  operating_income: "Operating income",
  net_income: "Net income",
  opex: "Operating expenses",
  debt: "Total debt",
  short_term_investments: "Short-term investments",
  restricted_cash: "Restricted cash",
  pipeline_depth_score: "Pipeline depth score",
  pipeline_concentration: "Pipeline concentration",
  clinical_momentum: "Clinical momentum",
  discontinuation_rate: "Discontinuation rate",
  rnd_per_late_stage_programme: "R&D per late-stage programme",
};

const BASIS_LABELS: Record<string, string> = {
  revenue_total: "total revenue",
  revenue_contracts_with_customers: "revenue from contracts with customers only",
  rnd_including_acquired_iprd: "including acquired IPR&D",
  rnd_excluding_acquired_iprd: "excluding acquired IPR&D",
  ocf_total: "including discontinued operations",
  ocf_continuing_operations: "continuing operations only",
};

export function conceptLabel(concept: string): string {
  return CONCEPT_LABELS[concept] ?? concept;
}

export function basisLabel(basis: string | null | undefined): string {
  if (!basis) return "not recorded";
  return BASIS_LABELS[basis] ?? basis;
}

/** Severity drives ordering only. Nothing here is hidden. */
export type Severity = "high" | "medium" | "low";

const SEVERITY: Record<string, Severity> = {
  no_tag_resolved: "high",
  no_quarters_derived: "high",
  stale_series: "high",
  restated_fiscal_year: "high",
  fy_reconciliation_failed: "high",
  overlapping_periods: "medium",
  basis_cutover: "medium",
  mixed_measurement_basis: "medium",
  chain_tags_diverge: "medium",
  tag_basis_uncertain: "medium",
  mixed_tags: "low",
  fallback_tag: "low",
};

export function severityOf(code: string): Severity {
  return SEVERITY[code] ?? "medium";
}

export const SEVERITY_ORDER: Record<Severity, number> = { high: 0, medium: 1, low: 2 };

export function describeFlag(record: QualityRecord): string {
  const concept = conceptLabel(record.concept);
  const d = record.detail ?? {};

  switch (record.code) {
    case "no_tag_resolved": {
      const near = (d.near_misses ?? []) as string[];
      const suffix = near.length
        ? ` The filer does report ${near.join(", ")}, which is not one of the tags this concept looks for.`
        : "";
      return `${concept} could not be resolved: this filer uses none of the XBRL tags defined for it.${suffix}`;
    }
    case "no_quarters_derived":
      return `${concept} has tagged facts but none that yield a discrete quarter — typically annual figures with no year-to-date periods to difference.`;
    case "stale_series":
      return `${concept} was last reported for ${d.latest_period_end}, but the filer has reported through ${d.reference_period_end} — ${d.days_behind} days behind. The tag (${d.tag}) appears to have been abandoned, so the most recent figures are missing rather than flat.`;
    case "basis_cutover":
      return `${concept} changes what it measures at this point: ${basisLabel(d.from_basis)} up to ${d.last_period_end_before}, then ${basisLabel(d.to_basis)} from ${d.first_period_end_after}. The step between those two periods is a change of definition, not of the underlying business.`;
    case "mixed_measurement_basis":
      return `${concept} is not measured on one consistent basis across this series. Figures either side of a cutover are not directly comparable.`;
    case "fy_reconciliation_failed":
      return `${concept} for the fiscal year ending ${d.fiscal_year_end} does not reconcile: the four quarters sum to ${d.quarters_sum}, while the filer reports ${d.annual} for the year — a difference of ${d.difference}. This is the signature of an annual restated after its quarters were filed.`;
    case "restated_fiscal_year":
      return `${concept} for this quarter belongs to a fiscal year whose annual figure was restated while the quarters were not. The quarter is reported as filed, but growth metrics spanning it are suppressed.`;
    case "chain_tags_diverge":
      return `${concept}: this filer reports this period under more than one tag with materially different values (${Object.entries(
        (d.values ?? {}) as Record<string, number>,
      )
        .map(([tag, v]) => `${tag} = ${v}`)
        .join("; ")}). The tags are not interchangeable for this filer.`;
    case "tag_basis_uncertain":
      return `${concept} for this period was derived from a period the candidate tags disagree about, so which measure it represents is ambiguous. It is reported on the ${basisLabel(
        d.measurement_basis,
      )} basis, from tag ${d.tag}, using the filer's own arithmetic.`;
    case "overlapping_periods":
      return `${concept}: this period overlapped its neighbour, because the filer was inconsistent about where the period starts. It was dropped to keep the series from double-counting, which leaves a gap here.`;
    case "fallback_tag":
      return `${concept} does not use its primary tag (${d.primary_tag}) throughout; it falls back to ${(
        (d.tags_used ?? []) as string[]
      ).join(", ")}.`;
    case "mixed_tags":
      return `${concept} is drawn from more than one XBRL tag across this series.`;
    case "cash_includes_restricted":
      return `${concept} was read from the cash-flow statement's reconciling figure, which includes restricted cash — the filer stopped tagging the balance-sheet figure that excludes it. For a cash position this overstates slightly. Anything dividing by a burn rate nets the restricted portion off, or declines to answer where the filer does not tag it separately.`;
    case "incomplete_sum":
      return `${concept} was summed from fewer components than it is defined by — typically a filer with no current maturities of long-term debt. A company that genuinely has none and one that failed to tag them are indistinguishable here.`;
    default:
      return `${concept}: ${record.code}${
        Object.keys(d).length ? ` ${JSON.stringify(d)}` : ""
      }`;
  }
}

/**
 * Why a metric produced no value.
 *
 * These are suppression reasons rather than data-quality flags: the fact layer
 * was fine, and the metric declined to answer. They need their own wording
 * because "we have no figure" and "the figure exists but is unreliable" are
 * different messages to a reader.
 */
export function describeReason(code: string, concept = "This metric"): string {
  switch (code) {
    case "not_meaningful_small_base":
      return `${concept} growth is not meaningful: the prior trailing year was too small for a percentage to describe the business rather than the base.`;
    case "restricted_cash_not_separable":
      return `Runway is suppressed: the cash figure includes restricted cash, and this filer does not tag the restricted portion separately. Restricted cash cannot fund operations, so dividing by a burn rate would overstate the runway.`;
    case "operating_cash_flow_positive":
      return `No runway figure: trailing operating cash flow is positive, so there is no burn rate to divide into. This is not a short runway — it is the absence of one.`;
    case "restated_fiscal_year":
      return `Suppressed because the window spans a fiscal year whose annual figure was restated while its quarters were not. A comparison across it would measure the restatement rather than the business.`;
    case "period_mismatch":
      return `No value: the two sides of this ratio do not cover the same twelve months, so dividing one by the other would describe neither. This is usually a concept whose tag was abandoned while the other side kept reporting.`;
    case "incomplete_window":
      return `No value: the twelve-month window does not tile cleanly, or the two sides of the ratio do not cover the same period.`;
    case "no_denominator":
      return `No value: neither revenue nor operating expenses were available as a denominator.`;
    case "no_cash_figure":
      return `No value: no cash balance could be resolved for this filer.`;
    case "no_active_trials":
      return `No value: this company has no active trials, so there is nothing to score.`;
    case "no_active_late_stage_trials":
      return `No value: no active Phase 2 or Phase 3 trials to divide R&D across. Common for device makers, whose studies carry no phase.`;
    case "too_few_resolved_trials":
      return `Discontinuation rate is suppressed below ten resolved trials: on a handful, one termination moves the rate by tens of percentage points and the figure describes the sample rather than the company.`;
    case "no_rnd_figure":
      return `No value: no trailing-twelve-month R&D figure to divide.`;
    case "cross_source_date_gap":
      return `This ratio spans two sources with different as-of dates — a trailing-twelve-month R&D figure ending on a fiscal quarter end, against a trial count taken from the registry at fetch time. The two were never true at the same instant.`;
    case "no_inputs":
      return `No value: the underlying series is empty.`;
    case "not_a_flow_concept":
      return `No value: this is a balance, and a balance has no growth rate over a trailing year.`;
    case "debt_not_tagged":
      return `Net cash treats debt as zero because this filer tags no borrowings. A debt-free company and one that failed to tag its debt look identical here.`;
    case "rnd_intensity_over_opex":
      return `R&D intensity is measured against operating expenses rather than revenue, because this company has no revenue. The two denominators are not comparable.`;
    case "cash_includes_restricted":
      return `The cash figure comes from the cash-flow statement and includes restricted cash.`;
    default:
      return code;
  }
}

/**
 * Render a pipeline value exactly as it arrived.
 *
 * No rounding, no thousands separators, no scaling. `null` renders as the word
 * null so a missing figure can never be mistaken for a zero or a dash.
 */
export function raw(value: unknown): string {
  if (value === null || value === undefined) return "null";
  return String(value);
}
