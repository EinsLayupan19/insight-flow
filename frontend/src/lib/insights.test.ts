import { describe, expect, it } from 'vitest'
import type { Insight, SalesInsights } from '../api/uploads'
import {
  coverageText,
  evidenceRows,
  formatDateRange,
  groupByImportance,
  insightColumnMapping,
  insightFormFields,
  insightOptionsFrom,
  summarizeFindings,
  thresholdLines,
} from './insights'

const THRESHOLDS = {
  min_rows_per_period: 5,
  min_periods_for_streak: 3,
  min_periods_for_range: 3,
  min_periods_for_unusual: 8,
  unusual_score: 3.5,
  max_unusual_periods: 3,
  high_change_percent: 20,
  medium_change_percent: 5,
  high_share_percent: 50,
  medium_share_percent: 25,
  medium_negative_percent: 5,
  concentration_target_percent: 80,
}

function finding(id: string, importance: Insight['importance'], overrides: Partial<Insight> = {}): Insight {
  return {
    id,
    kind: 'period_change',
    importance,
    title: id,
    statement: `${id}.`,
    evidence: [],
    caveats: [],
    questions: [],
    ...overrides,
  }
}

function insights(overrides: Partial<SalesInsights> = {}): SalesInsights {
  return {
    grain: 'month',
    columns_used: { order_date: 'order_date', product: 'product', category: null, order_id: 'order_id', quantity: null, unit_price: null, revenue: 'revenue' },
    definition: 'Findings compare complete months only.',
    thresholds: THRESHOLDS,
    coverage: { first_date: '2026-01-01', last_date: '2026-03-31', periods: 3, complete_periods: 3, partial_periods: [] },
    insights: [],
    not_assessed: [],
    caveats: [],
    ...overrides,
  }
}

describe('requests', () => {
  it('combines the trends and performance choices', () => {
    expect(insightOptionsFrom({ grain: 'week', dateColumn: 'Day' }, { productColumn: 'SKU', categoryColumn: '' })).toEqual({
      grain: 'week',
      dateColumn: 'Day',
      productColumn: 'SKU',
      categoryColumn: '',
    })
  })

  it('sends the grain and only the chosen columns', () => {
    const options = { grain: 'week' as const, dateColumn: 'Day', productColumn: '', categoryColumn: 'Dept' }

    expect(insightFormFields({ quantity: 'Qty', revenue: '' }, options)).toEqual({
      quantity_column: 'Qty',
      grain: 'week',
      order_date_column: 'Day',
      category_column: 'Dept',
    })
    expect(insightColumnMapping({ order_id: 'OrderNo' }, options)).toEqual({ order_id: 'OrderNo', order_date: 'Day', category: 'Dept' })
  })
})

describe('summaries', () => {
  it('counts findings and the checks that could not run', () => {
    const result = insights({
      insights: [finding('a', 'high'), finding('b', 'low')],
      not_assessed: [{ kind: 'unusual_period', title: 'Unusual periods', reason: 'Needs 8.' }],
    })

    expect(summarizeFindings(result)).toBe('2 findings, 1 of high importance. 1 check could not run.')
    expect(summarizeFindings(insights())).toBe('No findings for this file.')
  })

  it('describes which periods were compared', () => {
    expect(coverageText(insights())).toBe('By month: 3 complete months, Jan 1, 2026 to Mar 31, 2026.')
    const partial = insights({
      coverage: {
        first_date: '2026-01-05',
        last_date: '2026-03-06',
        periods: 3,
        complete_periods: 1,
        partial_periods: [
          { start: '2026-01-01', end: '2026-01-31', covered_from: '2026-01-05', covered_to: '2026-01-31' },
          { start: '2026-03-01', end: '2026-03-31', covered_from: '2026-03-01', covered_to: '2026-03-06' },
        ],
      },
    })
    expect(coverageText(partial)).toBe('By month: 1 complete month, Jan 5, 2026 to Mar 6, 2026 (2 partly covered months left out).')
    expect(coverageText(insights({ coverage: { first_date: null, last_date: null, periods: 0, complete_periods: 0, partial_periods: [] } }))).toBe(
      'By month: no usable dates.',
    )
  })

  it('formats date ranges as calendar dates in UTC', () => {
    expect(formatDateRange({ start: '2026-02-01', end: '2026-02-28' })).toBe('Feb 1, 2026 to Feb 28, 2026')
    expect(formatDateRange({ start: '2026-01-05', end: '2026-01-05' })).toBe('Jan 5, 2026')
  })

  it('groups findings by importance, keeping the API order within each group', () => {
    const groups = groupByImportance([finding('a', 'high'), finding('b', 'low'), finding('c', 'high')])

    expect(groups.map((group) => [group.importance, group.items.map((item) => item.id)])).toEqual([
      ['high', ['a', 'c']],
      ['low', ['b']],
    ])
  })

  it('lists the safeguards in plain words', () => {
    expect(thresholdLines(THRESHOLDS)).toEqual([
      'Only complete periods are compared, each with at least 5 rows.',
      'A streak needs at least 3 consecutive complete periods.',
      'Unusual periods are only looked for across at least 8 complete periods (robust score above 3.5).',
      'No percentage change is given from a zero or negative starting value.',
    ])
  })
})

describe('evidenceRows', () => {
  it('formats each figure with its metric name, periods, and rows', () => {
    const result = insights()
    const insight = finding('period_change.revenue', 'high', {
      evidence: [
        {
          metric: 'revenue',
          value: 120,
          previous: 150,
          change: -30,
          change_percent: -20,
          period: { start: '2026-03-01', end: '2026-03-31' },
          comparison_period: { start: '2026-02-01', end: '2026-02-28' },
          rows: 6,
          comparison_rows: 5,
          label: null,
        },
      ],
    })

    expect(evidenceRows(insight, result)).toEqual([
      {
        metric: 'Revenue',
        value: '120.00',
        previous: '150.00',
        change: '-30.00 (-20%)',
        period: 'Mar 1, 2026 to Mar 31, 2026',
        comparison: 'Feb 1, 2026 to Feb 28, 2026',
        rows: '6 vs 5',
      },
    ])
  })

  it('names gross sales, orders, shares, and labels', () => {
    const result = insights({ columns_used: { ...insights().columns_used, revenue: null, quantity: 'quantity', unit_price: 'unit_price' } })
    const insight = finding('mix', 'medium', {
      evidence: [
        { metric: 'revenue', value: 5, label: 'Tea' },
        { metric: 'orders', value: 3, previous: 2, change: 1, change_percent: null },
        { metric: 'revenue_share', value: 35.02, label: 'Mug' },
      ],
    })

    expect(evidenceRows(insight, result).map((row) => [row.metric, row.value, row.change])).toEqual([
      ['Gross sales (Tea)', '5.00', null],
      ['Orders', '3', '+1'],
      ['Share of gross sales (Mug)', '35.02%', null],
    ])
  })
})
