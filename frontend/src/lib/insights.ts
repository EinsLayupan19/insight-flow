// Key findings: request fields, summaries, and evidence formatting. Every finding, value, and
// sentence comes from the API (POST /api/uploads/csv/insights or a recorded "insights" analysis);
// this module only arranges and formats it.

import type { Grain, Insight, InsightDateRange, InsightThresholds, SalesInsights } from '../api/uploads'
import { explicitMapping, mappingFormFields, type ColumnMapping, type RecordedColumnMapping } from './columnMapping'
import { formatMetricValue, pluralize } from './format'
import type { PerformanceOptions } from './performance'
import { GRAIN_UNITS, type TrendOptions } from './trends'

/** The choices insights use: the trends' grain and date column, and the performance label columns. */
export type InsightOptions = { grain: Grain; dateColumn: string; productColumn: string; categoryColumn: string }
export const DEFAULT_INSIGHT_OPTIONS: InsightOptions = { grain: 'month', dateColumn: '', productColumn: '', categoryColumn: '' }

export function insightOptionsFrom(trends: TrendOptions, performance: PerformanceOptions): InsightOptions {
  return { grain: trends.grain, dateColumn: trends.dateColumn, ...performance }
}

/** Form fields for the in-memory endpoint. Only explicit column choices are sent. */
export function insightFormFields(mapping: ColumnMapping, options: InsightOptions): Record<string, string> {
  const fields: Record<string, string> = { ...mappingFormFields(mapping), grain: options.grain }
  if (options.dateColumn) fields.order_date_column = options.dateColumn
  if (options.productColumn) fields.product_column = options.productColumn
  if (options.categoryColumn) fields.category_column = options.categoryColumn
  return fields
}

/** The column mapping for a dataset insights analysis: explicit choices plus any chosen date and label columns. */
export function insightColumnMapping(mapping: ColumnMapping, options: InsightOptions): RecordedColumnMapping {
  const explicit: RecordedColumnMapping = explicitMapping(mapping)
  if (options.dateColumn) explicit.order_date = options.dateColumn
  if (options.productColumn) explicit.product = options.productColumn
  if (options.categoryColumn) explicit.category = options.categoryColumn
  return explicit
}

// ---------- Summaries ----------

export const IMPORTANCE_LABELS: Record<Insight['importance'], string> = { high: 'High importance', medium: 'Medium importance', low: 'Low importance' }
const IMPORTANCE_ORDER: readonly Insight['importance'][] = ['high', 'medium', 'low']

export function summarizeFindings(insights: SalesInsights): string {
  const findings = insights.insights
  if (findings.length === 0) return 'No findings for this file.'
  const high = findings.filter((item) => item.importance === 'high').length
  const skipped = insights.not_assessed.length
  const checks = skipped > 0 ? ` ${pluralize(skipped, 'check')} could not run.` : ''
  return `${pluralize(findings.length, 'finding')}, ${high} of high importance.${checks}`
}

const UTC_DAY = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' })

function dayText(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  return UTC_DAY.format(new Date(Date.UTC(year, month - 1, day)))
}

export function formatDateRange(range: InsightDateRange): string {
  return range.start === range.end ? dayText(range.start) : `${dayText(range.start)} to ${dayText(range.end)}`
}

/** Which periods the findings rest on, e.g. "By month: 3 complete months, Jan 1, 2026 to Mar 31, 2026." */
export function coverageText(insights: SalesInsights): string {
  const { coverage } = insights
  const unit = GRAIN_UNITS[insights.grain]
  const by = `By ${unit}`
  if (coverage.first_date === null || coverage.last_date === null) return `${by}: no usable dates.`
  const partial = coverage.partial_periods.length
  const left = partial > 0 ? ` (${pluralize(partial, `partly covered ${unit}`)} left out)` : ''
  return `${by}: ${pluralize(coverage.complete_periods, `complete ${unit}`)}, ${dayText(coverage.first_date)} to ${dayText(coverage.last_date)}${left}.`
}

export function groupByImportance(findings: readonly Insight[]): { importance: Insight['importance']; items: Insight[] }[] {
  return IMPORTANCE_ORDER.map((importance) => ({ importance, items: findings.filter((item) => item.importance === importance) })).filter(
    (group) => group.items.length > 0,
  )
}

export function thresholdLines(thresholds: InsightThresholds): string[] {
  return [
    `Only complete periods are compared, each with at least ${thresholds.min_rows_per_period} rows.`,
    `A streak needs at least ${thresholds.min_periods_for_streak} consecutive complete periods.`,
    `Unusual periods are only looked for across at least ${thresholds.min_periods_for_unusual} complete periods (robust score above ${thresholds.unusual_score}).`,
    'No percentage change is given from a zero or negative starting value.',
  ]
}

// ---------- Evidence ----------

export type EvidenceRow = {
  metric: string
  value: string | null
  previous: string | null
  change: string | null
  period: string | null
  comparison: string | null
  rows: string | null
}

const PERCENT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

function metricName(metric: string, insights: SalesInsights): string {
  const revenue = insights.columns_used.revenue !== null ? 'Revenue' : 'Gross sales'
  switch (metric) {
    case 'revenue':
      return revenue
    case 'orders':
      return 'Orders'
    case 'average_order_value':
      return 'Average order value'
    case 'revenue_share':
      return `Share of ${revenue.toLowerCase()}`
    case 'negative_revenue':
      return `Negative ${revenue.toLowerCase()}`
    default:
      return metric
  }
}

function formatValue(metric: string, value: number): string {
  if (metric === 'revenue_share') return `${PERCENT.format(value)}%`
  return formatMetricValue(value, metric === 'orders' ? 'count' : 'amount').text
}

/** One readable row per figure behind a finding. */
export function evidenceRows(insight: Insight, insights: SalesInsights): EvidenceRow[] {
  return insight.evidence.map((item) => {
    const name = metricName(item.metric, insights)
    const change =
      item.change === null || item.change === undefined
        ? null
        : `${item.change > 0 ? '+' : ''}${formatValue(item.metric, item.change)}${
            item.change_percent === null || item.change_percent === undefined ? '' : ` (${PERCENT.format(item.change_percent)}%)`
          }`
    const rows =
      item.rows === null || item.rows === undefined
        ? null
        : item.comparison_rows === null || item.comparison_rows === undefined
          ? String(item.rows)
          : `${item.rows} vs ${item.comparison_rows}`
    return {
      metric: item.label ? `${name} (${item.label})` : name,
      value: item.value === null ? null : formatValue(item.metric, item.value),
      previous: item.previous === null || item.previous === undefined ? null : formatValue(item.metric, item.previous),
      change,
      period: item.period ? formatDateRange(item.period) : null,
      comparison: item.comparison_period ? formatDateRange(item.comparison_period) : null,
      rows,
    }
  })
}
