import { describe, expect, it } from 'vitest'
import { formatBytes, formatDateTime, formatMetricValue, formatPercent, pluralize } from './format'

describe('formatDateTime', () => {
  it("shows an API timestamp in the reader's time zone", () => {
    expect(formatDateTime('2026-10-11T09:12:00.000+00:00', 'UTC')).toBe('Oct 11, 2026, 9:12 AM')
    expect(formatDateTime('2026-10-11T09:12:00.000+00:00', 'Asia/Manila')).toBe('Oct 11, 2026, 5:12 PM')
  })

  it('returns text it cannot read unchanged instead of "Invalid Date"', () => {
    expect(formatDateTime('not a date')).toBe('not a date')
  })
})

describe('formatMetricValue', () => {
  it('shows amounts with 2 decimals and says when that hides digits', () => {
    expect(formatMetricValue(140.95, 'amount')).toEqual({ text: '140.95', exact: '140.95', isRounded: false })
    expect(formatMetricValue(31.566666666666666, 'amount')).toEqual({
      text: '31.57',
      exact: '31.566666666666666',
      isRounded: true,
    })
  })

  it('pads whole amounts without calling them rounded', () => {
    expect(formatMetricValue(48, 'amount')).toEqual({ text: '48.00', exact: '48', isRounded: false })
  })

  it('groups thousands and keeps negative values', () => {
    expect(formatMetricValue(1234567.5, 'amount').text).toBe('1,234,567.50')
    expect(formatMetricValue(-0.1, 'amount')).toMatchObject({ text: '-0.10', isRounded: false })
  })

  it('shows quantities and counts without inventing decimals', () => {
    expect(formatMetricValue(15, 'quantity').text).toBe('15')
    expect(formatMetricValue(2.125, 'quantity')).toMatchObject({ text: '2.125', isRounded: false })
    expect(formatMetricValue(12000, 'count').text).toBe('12,000')
  })
})

describe('small formatters', () => {
  it('formats file sizes', () => {
    expect(formatBytes(1)).toBe('1 byte')
    expect(formatBytes(336)).toBe('336 bytes')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(10 * 1024 * 1024)).toBe('10.0 MB')
  })

  it('formats percentages the API already rounded', () => {
    expect(formatPercent(16.67)).toBe('16.67%')
    expect(formatPercent(0)).toBe('0%')
  })

  it('pluralizes with counts', () => {
    expect(pluralize(1, 'row')).toBe('1 row')
    expect(pluralize(1200, 'row')).toBe('1,200 rows')
    expect(pluralize(2, 'entry', 'entries')).toBe('2 entries')
  })
})
