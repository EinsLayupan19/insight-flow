import { describe, expect, it } from 'vitest'
import type { MetricResult, RetailMetrics } from '../api/uploads'
import { describeMetric, hasUnavailableMetrics, revenueBasis } from './metricDisplay'

function metric(overrides: Partial<MetricResult> = {}): MetricResult {
  return {
    status: 'calculated',
    value: 1,
    definition: 'definition',
    columns_used: [],
    rows_included: 1,
    rows_excluded: 0,
    notes: [],
    ...overrides,
  }
}

const unavailable = metric({ status: 'unavailable', value: null, rows_included: null, rows_excluded: null, notes: ['reason'] })

function metrics(overrides: Partial<RetailMetrics> = {}): RetailMetrics {
  return {
    columns_used: { order_id: 'order_id', quantity: 'quantity', unit_price: 'unit_price', revenue: null },
    number_rule: 'rule',
    row_count: metric(),
    total_quantity: metric(),
    total_revenue: metric({ columns_used: ['quantity', 'unit_price'] }),
    order_count: metric(),
    average_order_value: metric(),
    ...overrides,
  }
}

describe('revenueBasis', () => {
  it('is gross sales when revenue came from quantity x unit price', () => {
    expect(revenueBasis(metrics())).toBe('gross')
  })

  it('is recorded revenue when the revenue column was used', () => {
    const withRevenue = metrics({
      columns_used: { order_id: 'order_id', quantity: 'quantity', unit_price: 'unit_price', revenue: 'revenue' },
      total_revenue: metric({ columns_used: ['revenue'] }),
    })
    expect(revenueBasis(withRevenue)).toBe('recorded')
  })

  it('is unknown when revenue is unavailable', () => {
    expect(revenueBasis(metrics({ total_revenue: unavailable }))).toBeNull()
  })
})

describe('describeMetric', () => {
  it('labels gross sales as before discounts, returns, or refunds', () => {
    const presentation = describeMetric('total_revenue', 'gross')
    expect(presentation.label).toBe('Gross sales')
    expect(presentation.caption).toContain('before discounts, returns, or refunds')
  })

  it('labels a revenue column as recorded, not as gross or net', () => {
    expect(describeMetric('total_revenue', 'recorded').label).toBe('Revenue (as recorded)')
  })

  it('uses the right number format for each metric', () => {
    expect(describeMetric('average_order_value', 'gross').format).toBe('amount')
    expect(describeMetric('total_quantity', null).format).toBe('quantity')
    expect(describeMetric('order_count', null).format).toBe('count')
  })
})

describe('hasUnavailableMetrics', () => {
  it('is true when any metric is unavailable', () => {
    expect(hasUnavailableMetrics(metrics())).toBe(false)
    expect(hasUnavailableMetrics(metrics({ average_order_value: unavailable }))).toBe(true)
  })
})
