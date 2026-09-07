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
    default:
      return `${concept}: ${record.code}${
        Object.keys(d).length ? ` ${JSON.stringify(d)}` : ""
      }`;
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
