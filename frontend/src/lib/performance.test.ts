import { describe, expect, it } from 'vitest'
import type { Breakdown, PerformanceGroup, ProductPerformance } from '../api/uploads'
import {
  barScale,
  compareLabels,
  describeRankKey,
  formatShare,
  performanceColumnMapping,
  performanceFormFields,
  rankGroups,
  rankOptions,
  summarizeRanking,
  topGroups,
} from './performance'

function item(label: string, revenue: number | null, quantity: number | null = null, order_count: number | null = null): PerformanceGroup {
  return {
    label,
    row_count: 1,
    revenue,
    revenue_share: null,
    quantity,
    order_count,
    similar_labels: [],
    categories: [],
    product_count: null,
  }
}

const CALCULATED = {
  status: 'calculated' as const,
  value: 10,
  definition: 'Per product.',
  columns_used: ['revenue'],
  rows_included: 3,
  rows_excluded: 0,
  notes: [],
}
const UNAVAILABLE = { ...CALCULATED, status: 'unavailable' as const, value: null, rows_included: null, rows_excluded: null, notes: ['No column.'] }

function breakdown(groups: PerformanceGroup[], overrides: Partial<Breakdown> = {}): Breakdown {
  return {
    dimension: 'product',
    status: 'calculated',
    definition: 'One group per product.',
    columns_used: ['product'],
    rows_included: groups.length,
    rows_excluded: 0,
    notes: [],
    ranked_by: 'revenue',
    group_count: groups.length,
    groups,
    remaining: null,
    revenue: { ...CALCULATED, columns_used: ['quantity', 'unit_price'] },
    quantity: CALCULATED,
    order_count: CALCULATED,
    ...overrides,
  }
}

function performance(products: Breakdown): ProductPerformance {
  return {
    columns_used: { product: 'product', category: null, order_id: 'order_id', quantity: 'quantity', unit_price: 'unit_price', revenue: null },
    label_rule: 'Trimmed.',
    number_rule: 'Plain numbers.',
    products,
    categories: breakdown([], { dimension: 'category', status: 'unavailable', ranked_by: null }),
  }
}

describe('requests', () => {
  it('sends product and category columns only when chosen, with the explicit column choices', () => {
    expect(performanceFormFields({ quantity: 'Qty', revenue: '' }, { productColumn: 'SKU', categoryColumn: '' })).toEqual({
      quantity_column: 'Qty',
      product_column: 'SKU',
    })
    expect(performanceFormFields({}, { productColumn: '', categoryColumn: 'Dept' })).toEqual({ category_column: 'Dept' })
  })

  it('builds the dataset API mapping with the product and category roles', () => {
    expect(performanceColumnMapping({ order_id: 'OrderNo' }, { productColumn: 'SKU', categoryColumn: 'Dept' })).toEqual({
      order_id: 'OrderNo',
      product: 'SKU',
      category: 'Dept',
    })
    expect(performanceColumnMapping({}, { productColumn: '', categoryColumn: '' })).toEqual({})
  })
})

describe('ranking', () => {
  it('compares labels by code point, like the backend, so uppercase sorts first', () => {
    expect(['b', 'a', 'B'].sort(compareLabels)).toEqual(['B', 'a', 'b'])
  })

  it('ranks highest first, puts missing values last, and breaks ties by label', () => {
    const groups = [item('b', 10), item('none', null), item('B', 10), item('neg', -5), item('a', 10), item('top', 20)]

    expect(rankGroups(groups, 'revenue').map((g) => g.label)).toEqual(['top', 'B', 'a', 'b', 'neg', 'none'])
  })

  it('ranks by any measure without reordering the original list', () => {
    const groups = [item('Tea', 5, 1, 3), item('Mug', 9, 4, 1)]

    expect(rankGroups(groups, 'quantity').map((g) => g.label)).toEqual(['Mug', 'Tea'])
    expect(rankGroups(groups, 'order_count').map((g) => g.label)).toEqual(['Tea', 'Mug'])
    expect(groups.map((g) => g.label)).toEqual(['Tea', 'Mug'])
  })

  it('keeps the top groups for the chart', () => {
    const groups = Array.from({ length: 14 }, (_, i) => item(`P${i}`, 100 - i))

    expect(topGroups(groups, 'revenue', 10).map((g) => g.label)).toEqual(groups.slice(0, 10).map((g) => g.label))
    expect(topGroups(groups.slice(0, 3), 'revenue', 10)).toHaveLength(3)
  })

  it('offers only calculated measures, plus rows', () => {
    const b = breakdown([item('Tea', 1)], { order_count: UNAVAILABLE })

    expect(rankOptions(b)).toEqual(['revenue', 'quantity', 'row_count'])
  })

  it('offers only the server ranking when groups were left out by the 1,000-group cap', () => {
    const capped = breakdown([item('Tea', 1)], {
      ranked_by: 'revenue',
      group_count: 1001,
      remaining: { group_count: 1000, row_count: 1000, revenue: 5, quantity: 5, order_count: 5 },
    })

    expect(rankOptions(capped)).toEqual(['revenue'])
  })
})

describe('labels and formatting', () => {
  it('labels revenue by where it came from, like the metrics', () => {
    const result = performance(breakdown([item('Tea', 1)]))
    expect(describeRankKey('revenue', result.products, result).label).toBe('Gross sales')

    result.columns_used.revenue = 'revenue'
    const recorded = breakdown([item('Tea', 1)], { revenue: { ...CALCULATED, columns_used: ['revenue'] } })
    expect(describeRankKey('revenue', recorded, result).label).toBe('Revenue (as recorded)')
    expect(describeRankKey('order_count', recorded, result)).toMatchObject({ label: 'Orders', format: 'count' })
    expect(describeRankKey('row_count', recorded, result)).toMatchObject({ label: 'Rows', format: 'count' })
  })

  it('formats shares as percentages', () => {
    expect(formatShare(35.02)).toBe('35.02%')
    expect(formatShare(-4.5)).toBe('-4.5%')
    expect(formatShare(null)).toBeNull()
  })
})

describe('summarizeRanking', () => {
  it('describes the chart for screen readers', () => {
    const result = performance(breakdown([item('Mug', 36), item('Oat Milk', 22.8)]))

    expect(summarizeRanking(result.products, result, 'revenue', 10)).toBe(
      'Top 2 products by gross sales: Mug, 36.00; Oat Milk, 22.80.',
    )
  })

  it('says how many groups are not shown', () => {
    const groups = Array.from({ length: 12 }, (_, i) => item(`P${i}`, 12 - i))
    const result = performance(breakdown(groups))

    expect(summarizeRanking(result.products, result, 'revenue', 2)).toBe(
      'Top 2 products by gross sales: P0, 12.00; P1, 11.00. 10 more are in the table.',
    )
  })
})

describe('barScale', () => {
  it('starts positive bars at zero', () => {
    expect(barScale([36, 22.8, 4.25])).toEqual({ min: 0, max: 40, ticks: [0, 10, 20, 30, 40] })
  })

  it('extends left of zero for negative values', () => {
    expect(barScale([20, -10])).toEqual({ min: -10, max: 20, ticks: [-10, 0, 10, 20] })
  })

  it('still has a scale when every value is missing or zero', () => {
    expect(barScale([])).toEqual({ min: 0, max: 1, ticks: [0, 1] })
  })
})
