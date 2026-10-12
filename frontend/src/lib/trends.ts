// Sales trends: request fields, period labels, and the arithmetic behind the trend chart.
// Every value comes from the API (POST /api/uploads/csv/trends or a recorded "trends"
// analysis); this module only arranges and labels it.

import type { Grain, SalesTrends, TrendPeriod, TrendSeries } from '../api/uploads'
import { explicitMapping, mappingFormFields, type ColumnMapping, type TrendColumnMapping } from './columnMapping'
import { formatMetricValue, pluralize } from './format'
import { describeMetric, type MetricPresentation, type RevenueBasis } from './metricDisplay'

export const GRAINS: readonly Grain[] = ['day', 'week', 'month']
export const GRAIN_LABELS: Record<Grain, string> = { day: 'Day', week: 'Week', month: 'Month' }
export const GRAIN_UNITS: Record<Grain, string> = { day: 'day', week: 'week', month: 'month' }

/** What a trends request asks for. An empty dateColumn means "the column named order_date". */
export type TrendOptions = { grain: Grain; dateColumn: string }
export const DEFAULT_TREND_OPTIONS: TrendOptions = { grain: 'month', dateColumn: '' }

export function isSameTrendOptions(a: TrendOptions, b: TrendOptions): boolean {
  return a.grain === b.grain && a.dateColumn === b.dateColumn
}

// ---------- Requests ----------

/** Form fields for the in-memory endpoint. Only explicit column choices are sent. */
export function trendFormFields(mapping: ColumnMapping, options: TrendOptions): Record<string, string> {
  const fields: Record<string, string> = { ...mappingFormFields(mapping), grain: options.grain }
  if (options.dateColumn) fields.order_date_column = options.dateColumn
  return fields
}

/** The column mapping for a dataset trends analysis: explicit choices plus the date column, if chosen. */
export function trendColumnMapping(mapping: ColumnMapping, options: TrendOptions): TrendColumnMapping {
  const explicit: TrendColumnMapping = explicitMapping(mapping)
  if (options.dateColumn) explicit.order_date = options.dateColumn
  return explicit
}

// ---------- Period labels ----------
// Periods are calendar dates without a time zone. They are read and formatted in UTC so
// "2026-01-01" never shows as December 31 for a reader west of Greenwich.

const fmt = (options: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-US', { ...options, timeZone: 'UTC' })
const FULL_DAY = fmt({ month: 'short', day: 'numeric', year: 'numeric' })
const MONTH_DAY = fmt({ month: 'short', day: 'numeric' })
const LONG_MONTH = fmt({ month: 'long', year: 'numeric' })
const SHORT_MONTH = fmt({ month: 'short', year: 'numeric' })

function calendarDate(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day))
}

/** "Jan 5, 2026", "Jan 5 - 11, 2026", or "February 2026". */
export function formatPeriod(period: TrendPeriod, grain: Grain): string {
  const start = calendarDate(period.start)
  if (grain === 'day') return FULL_DAY.format(start)
  if (grain === 'month') return LONG_MONTH.format(start)

  const end = calendarDate(period.end)
  if (start.getUTCFullYear() !== end.getUTCFullYear()) return `${FULL_DAY.format(start)} - ${FULL_DAY.format(end)}`
  if (start.getUTCMonth() !== end.getUTCMonth()) {
    return `${MONTH_DAY.format(start)} - ${MONTH_DAY.format(end)}, ${end.getUTCFullYear()}`
  }
  return `${MONTH_DAY.format(start)} - ${end.getUTCDate()}, ${end.getUTCFullYear()}`
}

/** A short label for the chart's time axis. Days and weeks show the year only when the range spans years. */
export function axisLabel(period: TrendPeriod, grain: Grain, multiYear: boolean): string {
  const start = calendarDate(period.start)
  if (grain === 'month') return SHORT_MONTH.format(start)
  return multiYear ? FULL_DAY.format(start) : MONTH_DAY.format(start)
}

export function spansYears(periods: readonly TrendPeriod[]): boolean {
  return periods.length > 1 && periods[0].start.slice(0, 4) !== periods[periods.length - 1].end.slice(0, 4)
}

// ---------- Series ----------

export type TrendKey = 'revenue' | 'order_count' | 'average_order_value'
export const TREND_KEYS: readonly TrendKey[] = ['revenue', 'order_count', 'average_order_value']

function revenueBasisOf(trends: SalesTrends): RevenueBasis {
  if (trends.revenue.status !== 'calculated') return null
  const revenueColumn = trends.columns_used.revenue
  return revenueColumn !== null && trends.revenue.columns_used.includes(revenueColumn) ? 'recorded' : 'gross'
}

/** The same labels and number formats as the matching retail metric. */
export function describeTrendSeries(key: TrendKey, trends: SalesTrends): MetricPresentation {
  return describeMetric(key === 'revenue' ? 'total_revenue' : key, revenueBasisOf(trends))
}

/** One value per period (null where the API has none). */
export function seriesValues(series: TrendSeries, periodCount: number): (number | null)[] {
  if (series.status !== 'calculated' || series.points.length !== periodCount) return Array<null>(periodCount).fill(null)
  return series.points.map((point) => point.value)
}

// ---------- Table ----------

export type TrendCell =
  | { kind: 'value'; value: number; rowsIncluded: number }
  | { kind: 'no-rows' } // no row has a date in this period
  | { kind: 'not-usable' } // rows exist, but none had a usable value for this series
  | { kind: 'unavailable' } // the whole series could not be calculated

export type TrendTableRow = {
  start: string
  label: string
  rowCount: number
  cells: Record<TrendKey, TrendCell>
}

function cellFor(series: TrendSeries, index: number, period: TrendPeriod): TrendCell {
  if (series.status !== 'calculated') return { kind: 'unavailable' }
  if (period.row_count === 0) return { kind: 'no-rows' }
  const point = series.points[index]
  if (!point || point.value === null) return { kind: 'not-usable' }
  return { kind: 'value', value: point.value, rowsIncluded: point.rows_included }
}

export function trendTable(trends: SalesTrends): TrendTableRow[] {
  return trends.periods.map((period, index) => ({
    start: period.start,
    label: formatPeriod(period, trends.grain),
    rowCount: period.row_count,
    cells: {
      revenue: cellFor(trends.revenue, index, period),
      order_count: cellFor(trends.order_count, index, period),
      average_order_value: cellFor(trends.average_order_value, index, period),
    },
  }))
}

/** A text alternative for the chart: what is plotted, its range, and its extremes. */
export function summarizeTrend(trends: SalesTrends, key: TrendKey): string {
  const presentation = describeTrendSeries(key, trends)
  const heading = `${presentation.label} by ${GRAIN_UNITS[trends.grain]}`
  const { periods } = trends
  if (periods.length === 0) return `${heading}: no periods to chart.`
  const series = trends[key]
  if (series.status !== 'calculated') return `${heading}: not available. ${series.notes[0] ?? ''}`.trim()

  const label = (index: number) => formatPeriod(periods[index], trends.grain)
  const value = (index: number) => formatMetricValue(series.points[index].value as number, presentation.format).text
  const span = periods.length === 1 ? `1 period, ${label(0)}.` : `${pluralize(periods.length, 'period')} from ${label(0)} to ${label(periods.length - 1)}.`
  const parts = [`${heading}, ${span}`]

  const withValues = series.points.flatMap((point, index) => (point.value === null ? [] : [index]))
  if (withValues.length > 1) {
    const highest = withValues.reduce((best, index) => ((series.points[index].value as number) > (series.points[best].value as number) ? index : best))
    const lowest = withValues.reduce((best, index) => ((series.points[index].value as number) < (series.points[best].value as number) ? index : best))
    parts.push(`Highest: ${label(highest)}, ${value(highest)}. Lowest: ${label(lowest)}, ${value(lowest)}.`)
  } else if (withValues.length === 1) {
    parts.push(`Value: ${label(withValues[0])}, ${value(withValues[0])}.`)
  }

  const empty = periods.filter((period) => period.row_count === 0).length
  if (empty === 1) parts.push('1 period has no rows.')
  else if (empty > 1) parts.push(`${pluralize(empty, 'period')} have no rows.`)
  return parts.join(' ')
}

// ---------- Chart scale and layout ----------

function niceStep(raw: number): number {
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const fraction = raw / magnitude
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10
  return nice * magnitude
}

/** Clean tick values for the value axis. Always includes 0, because columns grow from a zero baseline. */
export function niceTicks(min: number, max: number, target = 4): number[] {
  const low = Math.min(0, min)
  const high = Math.max(0, max)
  if (low === high) return [0, 1]

  const step = niceStep((high - low) / target)
  const decimals = Math.max(0, -Math.floor(Math.log10(step))) + 1
  const first = Math.floor(low / step + 1e-9)
  const last = Math.ceil(high / step - 1e-9)
  const ticks: number[] = []
  for (let i = first; i <= last; i++) ticks.push(Number((i * step).toFixed(decimals)))
  return ticks
}

/** Which periods get an axis label: all of them when few, otherwise an even spread including both ends. */
export function pickTickIndexes(count: number, max: number): number[] {
  if (count <= max) return Array.from({ length: count }, (_, index) => index)
  return Array.from({ length: max }, (_, i) => Math.round((i * (count - 1)) / (max - 1)))
}

const COLUMN_GAP = 2
const MAX_COLUMN_WIDTH = 24
const MIN_COLUMN_BAND = 4

/** Each period's slot width, and its column: at most 24px, with a 2px gap to the next one. */
export function columnLayout(count: number, width: number): { band: number; barWidth: number } {
  const band = width / Math.max(count, 1)
  return { band, barWidth: Math.min(MAX_COLUMN_WIDTH, Math.max(1, band - COLUMN_GAP)) }
}

/**
 * SVG path for one column centered on `x`, from the baseline `y0` to the value `y1`.
 * Only the data end is rounded, so every column visibly grows from the same square baseline.
 */
export function columnPath(x: number, y0: number, y1: number, width: number, radius: number): string {
  const r = Math.min(radius, width / 2, Math.abs(y1 - y0))
  const left = x - width / 2
  const right = x + width / 2
  const up = y1 <= y0 // positive values grow upward (smaller y)
  const edge = up ? y1 + r : y1 - r
  return (
    `M${left},${y0} V${edge} Q${left},${y1} ${left + r},${y1} ` +
    `H${right - r} Q${right},${y1} ${right},${edge} V${y0} Z`
  )
}

/** Columns while each period has room for one; a line once periods are too dense to tell apart. */
export function chartMode(count: number, width: number): 'columns' | 'line' {
  return columnLayout(count, width).band >= MIN_COLUMN_BAND ? 'columns' : 'line'
}
