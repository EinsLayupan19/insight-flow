// How each retail metric from the API is labelled. Labels never change a value or its
// definition; the backend's own definition text is always shown next to them.

import type { RetailMetrics } from '../api/uploads'
import type { ValueFormat } from './format'

export type MetricKey = 'total_revenue' | 'order_count' | 'average_order_value' | 'total_quantity' | 'row_count'

/** Display order: the headline money figure first, the row count last. */
export const METRIC_ORDER: readonly MetricKey[] = [
  'total_revenue',
  'order_count',
  'average_order_value',
  'total_quantity',
  'row_count',
]

/** Where total revenue came from: a revenue column (as recorded) or quantity x unit price (gross sales). */
export type RevenueBasis = 'recorded' | 'gross' | null

export function revenueBasis(metrics: RetailMetrics): RevenueBasis {
  const revenue = metrics.total_revenue
  if (revenue.status !== 'calculated') return null
  const revenueColumn = metrics.columns_used.revenue
  return revenueColumn !== null && revenue.columns_used.includes(revenueColumn) ? 'recorded' : 'gross'
}

export type MetricPresentation = { label: string; caption: string | null; format: ValueFormat }

export function describeMetric(key: MetricKey, basis: RevenueBasis): MetricPresentation {
  switch (key) {
    case 'total_revenue':
      if (basis === 'recorded') {
        return { label: 'Revenue (as recorded)', caption: 'Sum of the revenue column, as it appears in the file', format: 'amount' }
      }
      if (basis === 'gross') {
        return { label: 'Gross sales', caption: 'Quantity × unit price, before discounts, returns, or refunds', format: 'amount' }
      }
      return { label: 'Revenue', caption: null, format: 'amount' }
    case 'average_order_value': {
      const caption = basis === 'gross' ? 'Based on gross sales' : basis === 'recorded' ? 'Based on recorded revenue' : null
      return { label: 'Average order value', caption, format: 'amount' }
    }
    case 'order_count':
      return { label: 'Orders', caption: 'Distinct order IDs', format: 'count' }
    case 'total_quantity':
      return { label: 'Total quantity', caption: 'Sum of the quantity column', format: 'quantity' }
    case 'row_count':
      return { label: 'Rows analyzed', caption: 'Data rows in the file', format: 'count' }
  }
}

/** True when at least one metric is unavailable because a column was not found. */
export function hasUnavailableMetrics(metrics: RetailMetrics): boolean {
  return METRIC_ORDER.some((key) => metrics[key].status === 'unavailable')
}
