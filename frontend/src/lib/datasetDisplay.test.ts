import { describe, expect, it } from 'vitest'
import type { AnalysisSummary } from '../api/datasets'
import { describeHighlights, describeMapping, selectedAnalysisId, shortHash } from './datasetDisplay'

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

describe('describeHighlights', () => {
  it('summarizes a data-quality check', () => {
    expect(describeHighlights(profile(1, 1, 5, 3))).toBe('1 duplicate row · 5 missing values · 3 type mismatches')
    expect(describeHighlights(profile(1, 0, 1, 1))).toBe('0 duplicate rows · 1 missing value · 1 type mismatch')
  })

  it('says "No findings" when the check found nothing', () => {
    expect(describeHighlights(profile(1, 0, 0, 0))).toBe('No findings')
  })

  it('summarizes a metrics calculation', () => {
    expect(describeHighlights(metrics(2, 1, 4))).toBe('1 of 5 metrics calculated')
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

describe('describeMapping', () => {
  it('lists explicit choices in role order', () => {
    expect(describeMapping({ unit_price: 'Price', quantity: 'Qty' })).toBe('Quantity → Qty, Unit price → Price')
  })

  it('lists a chosen date column first', () => {
    expect(describeMapping({ quantity: 'Qty', order_date: 'Day' })).toBe('Order date → Day, Quantity → Qty')
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
