import { describe, expect, it } from 'vitest'
import type { SalesTrends, TrendPeriod, TrendSeries } from '../api/uploads'
import {
  axisLabel,
  chartMode,
  columnLayout,
  columnPath,
  describeTrendSeries,
  formatPeriod,
  niceTicks,
  pickTickIndexes,
  seriesValues,
  summarizeTrend,
  trendColumnMapping,
  trendFormFields,
  trendTable,
} from './trends'

function period(start: string, end: string, row_count: number): TrendPeriod {
  return { start, end, row_count }
}

function series(values: (number | null)[], rows: number[]): TrendSeries {
  return {
    status: 'calculated',
    definition: 'Per period.',
    columns_used: ['revenue'],
    rows_included: rows.reduce((a, b) => a + b, 0),
    rows_excluded: 0,
    notes: [],
    points: values.map((value, index) => ({ value, rows_included: rows[index] })),
  }
}

const UNAVAILABLE: TrendSeries = {
  status: 'unavailable',
  definition: 'Distinct orders per period.',
  columns_used: [],
  rows_included: null,
  rows_excluded: null,
  notes: ["No column named 'order_id'."],
  points: [],
}

/** January and March have sales; February has no rows; March's orders have no usable IDs. */
function threeMonths(): SalesTrends {
  return {
    grain: 'month',
    columns_used: { order_date: 'order_date', order_id: null, quantity: 'quantity', unit_price: 'unit_price', revenue: null },
    date_rule: 'YYYY-MM-DD',
    number_rule: 'Plain numbers.',
    dated_rows: {
      status: 'calculated',
      value: 3,
      definition: 'Rows with a usable date.',
      columns_used: ['order_date'],
      rows_included: 3,
      rows_excluded: 0,
      notes: [],
    },
    periods: [period('2026-01-01', '2026-01-31', 2), period('2026-02-01', '2026-02-28', 0), period('2026-03-01', '2026-03-31', 1)],
    revenue: { ...series([140.95, null, -30], [2, 0, 1]), columns_used: ['quantity', 'unit_price'] },
    order_count: UNAVAILABLE,
    average_order_value: UNAVAILABLE,
  }
}

describe('requests', () => {
  it('sends the grain, explicit column choices, and a chosen date column as form fields', () => {
    expect(trendFormFields({ quantity: 'Qty', revenue: '' }, { grain: 'week', dateColumn: 'Day' })).toEqual({
      quantity_column: 'Qty',
      grain: 'week',
      order_date_column: 'Day',
    })
  })

  it('leaves the date column out when it is automatic', () => {
    expect(trendFormFields({}, { grain: 'month', dateColumn: '' })).toEqual({ grain: 'month' })
  })

  it('builds the dataset API mapping with the date role', () => {
    expect(trendColumnMapping({ order_id: 'OrderNo', unit_price: '' }, { grain: 'day', dateColumn: 'Day' })).toEqual({
      order_id: 'OrderNo',
      order_date: 'Day',
    })
    expect(trendColumnMapping({}, { grain: 'day', dateColumn: '' })).toEqual({})
  })
})

describe('period labels', () => {
  it('names a day, a month, and a week within one month', () => {
    expect(formatPeriod(period('2026-01-05', '2026-01-05', 1), 'day')).toBe('Jan 5, 2026')
    expect(formatPeriod(period('2026-02-01', '2026-02-28', 1), 'month')).toBe('February 2026')
    expect(formatPeriod(period('2026-01-05', '2026-01-11', 1), 'week')).toBe('Jan 5 - 11, 2026')
  })

  it('names weeks that cross a month or a year', () => {
    expect(formatPeriod(period('2026-01-26', '2026-02-01', 1), 'week')).toBe('Jan 26 - Feb 1, 2026')
    expect(formatPeriod(period('2025-12-29', '2026-01-04', 1), 'week')).toBe('Dec 29, 2025 - Jan 4, 2026')
  })

  it('reads dates as calendar dates, never shifted by the time zone', () => {
    // 2026-01-01 at UTC midnight is still December 31 in the Americas.
    expect(formatPeriod(period('2026-01-01', '2026-01-31', 1), 'month')).toBe('January 2026')
    expect(axisLabel(period('2026-01-01', '2026-01-01', 1), 'day', false)).toBe('Jan 1')
  })

  it('keeps axis labels short and adds the year when the range spans years', () => {
    expect(axisLabel(period('2026-03-01', '2026-03-31', 1), 'month', false)).toBe('Mar 2026')
    expect(axisLabel(period('2026-01-05', '2026-01-11', 1), 'week', false)).toBe('Jan 5')
    expect(axisLabel(period('2026-01-05', '2026-01-11', 1), 'week', true)).toBe('Jan 5, 2026')
  })
})

describe('series presentation', () => {
  it('labels revenue by where it came from, like the metrics', () => {
    const trends = threeMonths()
    expect(describeTrendSeries('revenue', trends).label).toBe('Gross sales')

    trends.columns_used.revenue = 'revenue'
    trends.revenue = { ...trends.revenue, columns_used: ['revenue'] }
    expect(describeTrendSeries('revenue', trends).label).toBe('Revenue (as recorded)')
    expect(describeTrendSeries('order_count', trends)).toMatchObject({ label: 'Orders', format: 'count' })
  })

  it('aligns values with periods, keeping missing values as null', () => {
    expect(seriesValues(threeMonths().revenue, 3)).toEqual([140.95, null, -30])
    expect(seriesValues(UNAVAILABLE, 3)).toEqual([null, null, null])
  })
})

describe('trendTable', () => {
  it('tells apart a value, a period without rows, rows without a usable value, and an unavailable trend', () => {
    const trends = threeMonths()
    trends.revenue.points[2] = { value: null, rows_included: 0 }

    const rows = trendTable(trends)

    expect(rows.map((row) => row.label)).toEqual(['January 2026', 'February 2026', 'March 2026'])
    expect(rows[0].cells.revenue).toEqual({ kind: 'value', value: 140.95, rowsIncluded: 2 })
    expect(rows[1].cells.revenue).toEqual({ kind: 'no-rows' })
    expect(rows[2].cells.revenue).toEqual({ kind: 'not-usable' })
    expect(rows[0].cells.order_count).toEqual({ kind: 'unavailable' })
    expect(rows.map((row) => row.rowCount)).toEqual([2, 0, 1])
  })
})

describe('summarizeTrend', () => {
  it('describes the chart for screen readers, including the highest and lowest periods', () => {
    expect(summarizeTrend(threeMonths(), 'revenue')).toBe(
      'Gross sales by month, 3 periods from January 2026 to March 2026. ' +
        'Highest: January 2026, 140.95. Lowest: March 2026, -30.00. 1 period has no rows.',
    )
  })

  it('says when there is nothing to chart', () => {
    const trends = threeMonths()
    trends.periods = []
    trends.revenue = UNAVAILABLE
    // Without a calculated revenue series there is no basis to call it gross or recorded.
    expect(summarizeTrend(trends, 'revenue')).toBe('Revenue by month: no periods to chart.')
  })
})

describe('chart scale', () => {
  it('rounds the value axis to clean steps that include zero', () => {
    expect(niceTicks(0, 140.95)).toEqual([0, 50, 100, 150])
    expect(niceTicks(12, 30)).toEqual([0, 10, 20, 30])
  })

  it('extends below zero for negative values', () => {
    expect(niceTicks(-30, 50)).toEqual([-40, -20, 0, 20, 40, 60])
    expect(niceTicks(-5, -1)).toEqual([-6, -4, -2, 0])
  })

  it('still draws an axis when every value is zero or there are none', () => {
    expect(niceTicks(0, 0)).toEqual([0, 1])
  })

  it('handles small decimal values', () => {
    expect(niceTicks(0, 0.3)).toEqual([0, 0.1, 0.2, 0.3])
  })
})

describe('chart layout', () => {
  it('labels every period when there are few, and an even spread including both ends when there are many', () => {
    expect(pickTickIndexes(3, 6)).toEqual([0, 1, 2])
    expect(pickTickIndexes(12, 6)).toEqual([0, 2, 4, 7, 9, 11])
    expect(pickTickIndexes(1, 6)).toEqual([0])
    expect(pickTickIndexes(0, 6)).toEqual([])
  })

  it('caps columns at 24px and keeps a 2px gap between them', () => {
    expect(columnLayout(3, 600)).toEqual({ band: 200, barWidth: 24 })
    expect(columnLayout(100, 600)).toEqual({ band: 6, barWidth: 4 })
  })

  it('rounds only the data end of a column, never the baseline', () => {
    // A positive column grows up from the baseline at y=100: rounded top, square bottom.
    expect(columnPath(50, 100, 40, 24, 4)).toBe('M38,100 V44 Q38,40 42,40 H58 Q62,40 62,44 V100 Z')
    // A negative column grows down: rounded bottom, square top.
    expect(columnPath(50, 100, 160, 24, 4)).toBe('M38,100 V156 Q38,160 42,160 H58 Q62,160 62,156 V100 Z')
    // A column shorter than the radius uses a smaller radius instead of overshooting.
    expect(columnPath(50, 100, 98, 24, 4)).toBe('M38,100 V100 Q38,98 40,98 H60 Q62,98 62,100 V100 Z')
  })

  it('draws columns while they stay readable, and a line once periods are too dense', () => {
    expect(chartMode(30, 600)).toBe('columns')
    expect(chartMode(400, 600)).toBe('line')
  })
})
