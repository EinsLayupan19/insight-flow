// Wording for saved datasets and their analysis history. Every number comes from the API.

import type { AnalysisSummary } from '../api/datasets'
import { METRIC_ROLES, ORDER_DATE_LABEL, ROLE_LABELS, type TrendColumnMapping } from './columnMapping'
import { pluralize } from './format'
import { GRAIN_UNITS } from './trends'

export const ANALYSIS_TITLES = {
  profile: 'Data-quality check',
  metrics: 'Retail metrics',
  trends: 'Sales trends',
} as const

/** One line describing an analysis' headline numbers. */
export function describeHighlights(analysis: AnalysisSummary): string {
  if (analysis.kind === 'profile') {
    const { duplicate_row_count, missing_value_count, type_mismatch_count } = analysis.highlights
    if (duplicate_row_count + missing_value_count + type_mismatch_count === 0) return 'No findings'
    return [
      pluralize(duplicate_row_count, 'duplicate row'),
      pluralize(missing_value_count, 'missing value'),
      pluralize(type_mismatch_count, 'type mismatch', 'type mismatches'),
    ].join(' · ')
  }
  if (analysis.kind === 'trends') {
    const { grain, period_count, calculated_count, unavailable_count } = analysis.highlights
    const periods = period_count === 0 ? 'No periods' : pluralize(period_count, GRAIN_UNITS[grain])
    return `${periods} · ${calculated_count} of ${calculated_count + unavailable_count} trends calculated`
  }
  const { calculated_count, unavailable_count } = analysis.highlights
  return `${calculated_count} of ${calculated_count + unavailable_count} metrics calculated`
}

/** "Automatic column matching", or the explicit choices, e.g. "Quantity → Qty, Unit price → Price". */
export function describeMapping(mapping: TrendColumnMapping): string {
  const choices = METRIC_ROLES.filter((role) => mapping[role]).map((role) => `${ROLE_LABELS[role]} → ${mapping[role]}`)
  if (mapping.order_date) choices.unshift(`${ORDER_DATE_LABEL} → ${mapping.order_date}`)
  return choices.length > 0 ? choices.join(', ') : 'Automatic column matching'
}

/** The analysis to show: the one in the URL, otherwise the newest. */
export function selectedAnalysisId(analyses: readonly AnalysisSummary[] | null, requested: number | null): number | null {
  if (requested !== null) return requested
  return analyses && analyses.length > 0 ? analyses[0].id : null
}

/** The first 12 characters of a SHA-256 hash, enough to tell files apart at a glance. */
export function shortHash(sha256: string): string {
  return sha256.slice(0, 12)
}
