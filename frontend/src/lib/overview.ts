// Short summaries for the Overview page. They only count and order what the API returned;
// the full reports, with their evidence, are on the Analytics page.

import type { Insight, QualityReport, SalesInsights } from '../api/uploads'
import { pluralize } from './format'
import { groupByImportance } from './insights'

/** One line on what the data-quality checks found. */
export function qualitySummary(report: QualityReport): { clean: boolean; text: string } {
  const withMissing = report.columns.filter((column) => column.missing_count > 0)
  const withMismatches = report.columns.filter((column) => column.mismatch_count > 0)
  const missing = withMissing.reduce((total, column) => total + column.missing_count, 0)
  const mismatches = withMismatches.reduce((total, column) => total + column.mismatch_count, 0)

  const parts: string[] = []
  if (report.duplicate_row_count > 0) parts.push(pluralize(report.duplicate_row_count, 'duplicate row'))
  if (missing > 0) parts.push(`${pluralize(missing, 'missing value')} in ${pluralize(withMissing.length, 'column')}`)
  if (mismatches > 0) {
    parts.push(`${pluralize(mismatches, 'value')} in the wrong format in ${pluralize(withMismatches.length, 'column')}`)
  }

  if (parts.length === 0) return { clean: true, text: 'No duplicate rows, missing values, or values in the wrong format.' }
  return { clean: false, text: `${parts.join(', ')}.` }
}

/** The first few findings, most important first. */
export function topFindings(insights: SalesInsights, limit: number): Insight[] {
  return groupByImportance(insights.insights)
    .flatMap((group) => group.items)
    .slice(0, limit)
}
