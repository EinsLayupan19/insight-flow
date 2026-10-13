import { describe, expect, it } from 'vitest'
import type { ColumnProfile, Insight, QualityReport, SalesInsights } from '../api/uploads'
import { qualitySummary, topFindings } from './overview'

function column(name: string, missing: number, mismatches: number): ColumnProfile {
  return {
    name,
    missing_count: missing,
    missing_percent: missing,
    inferred_type: 'integer',
    type_counts: {},
    mismatch_count: mismatches,
    mismatch_examples: [],
  }
}

function report(duplicates: number, columns: ColumnProfile[]): QualityReport {
  return {
    row_count: 100,
    column_count: columns.length,
    duplicate_row_count: duplicates,
    duplicate_row_percent: duplicates,
    duplicate_examples: [],
    columns,
    definitions: {},
  }
}

describe('qualitySummary', () => {
  it('reports a clean file', () => {
    expect(qualitySummary(report(0, [column('a', 0, 0), column('b', 0, 0)]))).toEqual({
      clean: true,
      text: 'No duplicate rows, missing values, or values in the wrong format.',
    })
  })

  it('adds up what the checks found, with the columns involved', () => {
    const summary = qualitySummary(report(2, [column('a', 3, 0), column('b', 1, 4), column('c', 0, 1)]))
    expect(summary).toEqual({
      clean: false,
      text: '2 duplicate rows, 4 missing values in 2 columns, 5 values in the wrong format in 2 columns.',
    })
  })

  it('leaves out checks that found nothing', () => {
    expect(qualitySummary(report(0, [column('a', 1, 0)])).text).toBe('1 missing value in 1 column.')
    expect(qualitySummary(report(1, [column('a', 0, 0)])).text).toBe('1 duplicate row.')
  })
})

function insight(id: string, importance: Insight['importance']): Insight {
  return { id, kind: 'range', importance, title: id, statement: '', evidence: [], caveats: [], questions: [] }
}

function insights(items: Insight[]): SalesInsights {
  return {
    grain: 'month',
    columns_used: {} as SalesInsights['columns_used'],
    definition: '',
    thresholds: {} as SalesInsights['thresholds'],
    coverage: { first_date: null, last_date: null, periods: 0, complete_periods: 0, partial_periods: [] },
    insights: items,
    not_assessed: [],
    caveats: [],
  }
}

describe('topFindings', () => {
  it('keeps the most important findings first', () => {
    const data = insights([insight('low-1', 'low'), insight('high-1', 'high'), insight('medium-1', 'medium'), insight('high-2', 'high')])
    expect(topFindings(data, 3).map((item) => item.id)).toEqual(['high-1', 'high-2', 'medium-1'])
  })

  it('returns fewer when there are fewer findings', () => {
    expect(topFindings(insights([insight('only', 'low')]), 3).map((item) => item.id)).toEqual(['only'])
    expect(topFindings(insights([]), 3)).toEqual([])
  })
})
