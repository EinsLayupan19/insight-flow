import { describe, expect, it } from 'vitest'
import type { AnalysisSummary } from '../api/datasets'
import { ANALYSIS_TITLES, describeHighlights, describeMapping, selectedAnalysisId, shortHash } from './datasetDisplay'

const base = { dataset_id: 1, created_at: '2026-10-11T09:12:00.000+00:00', app_version: '0.1.0', column_mapping: {} }

function profile(id: number, duplicates: number, missing: number, mismatches: number): AnalysisSummary {
  return {
    ...base,
    id,
    kind: 'profile',
    highlights: { duplicate_row_count: duplicates, missing_value_count: missing, type_mismatch_count: mismatches },
  }
}

function metrics(id: number, calculated: number, unavailable: number): AnalysisSummary {
  return { ...base, id, kind: 'metrics', highlights: { calculated_count: calculated, unavailable_count: unavailable } }
}

describe('ANALYSIS_TITLES', () => {
  it('names each kind of analysis in plain words', () => {
    expect(ANALYSIS_TITLES).toEqual({
      profile: 'Data-quality check',
      metrics: 'Key numbers',
      trends: 'Sales trends',
      performance: 'Products and categories',
      insights: 'Key findings',
    })
  })
})

describe('describeHighlights', () => {
  it('summarizes a data-quality check', () => {
    expect(describeHighlights(profile(1, 1, 5, 3))).toBe('1 duplicate row · 5 missing values · 3 values in the wrong format')
    expect(describeHighlights(profile(1, 0, 1, 1))).toBe('0 duplicate rows · 1 missing value · 1 value in the wrong format')
  })

  it('says "No findings" when the check found nothing', () => {
    expect(describeHighlights(profile(1, 0, 0, 0))).toBe('No findings')
  })

  it('summarizes a metrics calculation', () => {
    expect(describeHighlights(metrics(2, 1, 4))).toBe('1 of 5 key numbers calculated')
  })
})

describe('describeHighlights for trends', () => {
  it('names the periods and how many trends were calculated', () => {
    const trends = (grain: 'day' | 'week' | 'month', periods: number, calculated: number): AnalysisSummary => ({
      ...base,
      id: 3,
      kind: 'trends',
      highlights: { grain, period_count: periods, calculated_count: calculated, unavailable_count: 3 - calculated },
    })

    expect(describeHighlights(trends('month', 12, 3))).toBe('12 months · 3 of 3 trends calculated')
    expect(describeHighlights(trends('day', 1, 1))).toBe('1 day · 1 of 3 trends calculated')
    expect(describeHighlights(trends('week', 0, 0))).toBe('No periods · 0 of 3 trends calculated')
  })
})

describe('describeHighlights for insights', () => {
  it('counts findings, high-importance ones, and checks that could not run', () => {
    const insights = (finding_count: number, high_count: number, not_assessed_count: number): AnalysisSummary => ({
      ...base,
      id: 5,
      kind: 'insights',
      highlights: { grain: 'month', finding_count, high_count, not_assessed_count },
    })

    expect(describeHighlights(insights(4, 2, 3))).toBe("4 findings · 2 high · 3 checks couldn't run")
    expect(describeHighlights(insights(1, 0, 0))).toBe('1 finding')
    expect(describeHighlights(insights(0, 0, 5))).toBe("No findings · 5 checks couldn't run")
  })
})

describe('describeHighlights for performance', () => {
  it('names how many products and categories were found, or which breakdown is unavailable', () => {
    const performance = (product_count: number | null, category_count: number | null): AnalysisSummary => ({
      ...base,
      id: 4,
      kind: 'performance',
      highlights: { product_count, category_count },
    })

    expect(describeHighlights(performance(48, 6))).toBe('48 products · 6 categories')
    expect(describeHighlights(performance(1, null))).toBe('1 product · categories unavailable')
    expect(describeHighlights(performance(null, null))).toBe('Products and categories unavailable')
  })
})

describe('describeMapping', () => {
  it('lists explicit choices in role order', () => {
    expect(describeMapping({ unit_price: 'Price', quantity: 'Qty' })).toBe('Quantity → Qty, Unit price → Price')
  })

  it('lists a chosen date column first', () => {
    expect(describeMapping({ quantity: 'Qty', order_date: 'Day' })).toBe('Order date → Day, Quantity → Qty')
  })

  it('lists chosen product and category columns first', () => {
    expect(describeMapping({ revenue: 'Amount', category: 'Dept', product: 'SKU' })).toBe(
      'Product → SKU, Category → Dept, Revenue → Amount',
    )
  })

  it('names automatic matching when nothing was chosen', () => {
    expect(describeMapping({})).toBe('Automatic column matching')
    expect(describeMapping({ revenue: '' })).toBe('Automatic column matching')
  })
})

describe('selectedAnalysisId', () => {
  const history = [metrics(9, 5, 0), profile(4, 0, 0, 0)]

  it('uses the analysis in the URL', () => {
    expect(selectedAnalysisId(history, 4)).toBe(4)
  })

  it('falls back to the newest analysis', () => {
    expect(selectedAnalysisId(history, null)).toBe(9)
  })

  it('selects nothing while the history is loading or empty', () => {
    expect(selectedAnalysisId(null, null)).toBeNull()
    expect(selectedAnalysisId([], null)).toBeNull()
  })
})

describe('shortHash', () => {
  it('keeps the first 12 characters', () => {
    expect(shortHash('0123456789abcdef'.repeat(4))).toBe('0123456789ab')
  })
})
