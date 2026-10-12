// Product and category performance: request fields, ranking, labels, and the bar chart's scale.
// Every value comes from the API (POST /api/uploads/csv/performance or a recorded "performance"
// analysis); this module only orders and labels it, with the backend's tie-break rule.

import type { Breakdown, PerformanceGroup, ProductPerformance } from '../api/uploads'
import { explicitMapping, mappingFormFields, type ColumnMapping, type RecordedColumnMapping } from './columnMapping'
import { formatMetricValue } from './format'
import { describeMetric, type MetricPresentation, type RevenueBasis } from './metricDisplay'
import { niceTicks } from './trends'

/** Which columns hold the labels. An empty string means "the column named product / category". */
export type PerformanceOptions = { productColumn: string; categoryColumn: string }
export const DEFAULT_PERFORMANCE_OPTIONS: PerformanceOptions = { productColumn: '', categoryColumn: '' }

export type Dimension = 'product' | 'category'
export const DIMENSION_LABELS: Record<Dimension, { singular: string; plural: string; title: string }> = {
  product: { singular: 'product', plural: 'products', title: 'Products' },
  category: { singular: 'category', plural: 'categories', title: 'Categories' },
}

// ---------- Requests ----------

/** Form fields for the in-memory endpoint. Only explicit column choices are sent. */
export function performanceFormFields(mapping: ColumnMapping, options: PerformanceOptions): Record<string, string> {
  const fields = mappingFormFields(mapping)
  if (options.productColumn) fields.product_column = options.productColumn
  if (options.categoryColumn) fields.category_column = options.categoryColumn
  return fields
}

/** The column mapping for a dataset performance analysis: explicit choices plus chosen label columns. */
export function performanceColumnMapping(mapping: ColumnMapping, options: PerformanceOptions): RecordedColumnMapping {
  const explicit: RecordedColumnMapping = explicitMapping(mapping)
  if (options.productColumn) explicit.product = options.productColumn
  if (options.categoryColumn) explicit.category = options.categoryColumn
  return explicit
}

// ---------- Ranking ----------

export type RankKey = 'revenue' | 'quantity' | 'order_count' | 'row_count'
const RANK_KEYS: readonly RankKey[] = ['revenue', 'quantity', 'order_count', 'row_count']

/** Code point order, the same order DuckDB uses for ties, so the page never disagrees with the API. */
export function compareLabels(a: string, b: string): number {
  const left = Array.from(a)
  const right = Array.from(b)
  for (let i = 0; i < Math.min(left.length, right.length); i++) {
    const difference = (left[i].codePointAt(0) ?? 0) - (right[i].codePointAt(0) ?? 0)
    if (difference !== 0) return difference
  }
  return left.length - right.length
}

/** Highest first; groups without a value last; ties broken by label. Returns a new array. */
export function rankGroups(groups: readonly PerformanceGroup[], key: RankKey): PerformanceGroup[] {
  return [...groups].sort((a, b) => {
    const x = a[key]
    const y = b[key]
    if (x !== y) {
      if (x === null) return 1
      if (y === null) return -1
      return y - x
    }
    return compareLabels(a.label, b.label)
  })
}

export function topGroups(groups: readonly PerformanceGroup[], key: RankKey, count: number): PerformanceGroup[] {
  return rankGroups(groups, key).slice(0, count)
}

/**
 * The measures a breakdown can be ranked by. When groups were left out by the 1,000-group cap,
 * only the API's own ranking is offered: re-ranking the listed groups could miss the real top ones.
 */
export function rankOptions(breakdown: Breakdown): RankKey[] {
  if (breakdown.remaining !== null && breakdown.ranked_by !== null) return [breakdown.ranked_by]
  return RANK_KEYS.filter((key) => key === 'row_count' || breakdown[key].status === 'calculated')
}

// ---------- Labels ----------

function revenueBasis(breakdown: Breakdown, performance: ProductPerformance): RevenueBasis {
  if (breakdown.revenue.status !== 'calculated') return null
  const revenueColumn = performance.columns_used.revenue
  return revenueColumn !== null && breakdown.revenue.columns_used.includes(revenueColumn) ? 'recorded' : 'gross'
}

/** The same labels and number formats as the matching retail metric. */
export function describeRankKey(key: RankKey, breakdown: Breakdown, performance: ProductPerformance): MetricPresentation {
  switch (key) {
    case 'revenue':
      return describeMetric('total_revenue', revenueBasis(breakdown, performance))
    case 'quantity':
      return describeMetric('total_quantity', null)
    case 'order_count':
      return describeMetric('order_count', null)
    case 'row_count':
      return { label: 'Rows', caption: null, format: 'count' }
  }
}

const SHARE = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

export function formatShare(share: number | null): string | null {
  return share === null ? null : `${SHARE.format(share)}%`
}

/** A text alternative for the bar chart: what is ranked and the values shown. */
export function summarizeRanking(breakdown: Breakdown, performance: ProductPerformance, key: RankKey, count: number): string {
  const presentation = describeRankKey(key, breakdown, performance)
  const plural = DIMENSION_LABELS[breakdown.dimension].plural
  const shown = topGroups(breakdown.groups, key, count)
  const values = shown.map((group) => {
    const value = group[key]
    return `${group.label}, ${value === null ? 'no value' : formatMetricValue(value, presentation.format).text}`
  })
  const hidden = breakdown.group_count - shown.length
  const more = hidden > 0 ? ` ${hidden} more ${hidden === 1 ? 'is' : 'are'} in the table.` : ''
  return `Top ${shown.length} ${plural} by ${presentation.label.toLowerCase()}: ${values.join('; ')}.${more}`
}

// ---------- Bar chart scale ----------

/** A value axis that always includes zero, so every bar grows from the same baseline. */
export function barScale(values: readonly number[]): { min: number; max: number; ticks: number[] } {
  const ticks = niceTicks(Math.min(0, ...values), Math.max(0, ...values))
  return { min: ticks[0], max: ticks[ticks.length - 1], ticks }
}
