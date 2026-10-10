// Number formatting for the dashboard. Formatting is for display only: the exact
// value from the API is kept alongside so rounding is never hidden.

const COUNT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const QUANTITY = new Intl.NumberFormat('en-US', { maximumFractionDigits: 8 })
const AMOUNT = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const PERCENT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 })

export function formatCount(value: number): string {
  return COUNT.format(value)
}

/** "1 row", "2 rows". */
export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${formatCount(count)} ${count === 1 ? singular : plural}`
}

/** The API already rounds percentages to 2 decimals; this only adds grouping and the sign. */
export function formatPercent(value: number): string {
  return `${PERCENT.format(value)}%`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return pluralize(bytes, 'byte')
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export type ValueFormat = 'count' | 'quantity' | 'amount'
export type FormattedValue = { text: string; exact: string; isRounded: boolean }

/** Format a metric value. `isRounded` is true when the display hides digits of the exact value. */
export function formatMetricValue(value: number, format: ValueFormat): FormattedValue {
  const formatter = format === 'amount' ? AMOUNT : format === 'quantity' ? QUANTITY : COUNT
  const text = formatter.format(value)
  return { text, exact: String(value), isRounded: Number(text.replaceAll(',', '')) !== value }
}
