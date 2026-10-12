// Calls the CSV analysis endpoints in backend/app/api/uploads.py. Each call sends the
// file as multipart form data in the field named "file". The backend reads the file
// in memory, analyzes it, and discards it: nothing is stored between requests, so
// every analysis step uploads the file again.

import { mappingFormFields, type ColumnMapping, type MetricRole } from '../lib/columnMapping'
import { performanceFormFields, type PerformanceOptions } from '../lib/performance'
import { trendFormFields, type TrendOptions } from '../lib/trends'
import { isObject, requestJson } from './http'

// ---------- Response types (mirror the backend's Pydantic response models) ----------

export type CsvUploadResponse = {
  filename: string
  size_bytes: number
  row_count: number
  column_count: number
  columns: string[]
}

export type ValueType = 'boolean' | 'integer' | 'decimal' | 'date' | 'datetime' | 'text'
export type InferredType = ValueType | 'empty'

export type ValueExample = { line: number; value: string }
export type DuplicateExample = { line: number; duplicate_of_line: number }

export type ColumnProfile = {
  name: string
  missing_count: number
  missing_percent: number
  inferred_type: InferredType
  type_counts: Partial<Record<ValueType, number>>
  mismatch_count: number
  mismatch_examples: ValueExample[]
}

export type QualityReport = {
  row_count: number
  column_count: number
  duplicate_row_count: number
  duplicate_row_percent: number
  duplicate_examples: DuplicateExample[]
  columns: ColumnProfile[]
  definitions: Record<string, string>
}

export type CsvProfileResponse = { filename: string; size_bytes: number; profile: QualityReport }

export type MetricResult = {
  status: 'calculated' | 'unavailable'
  value: number | null
  definition: string
  columns_used: string[]
  rows_included: number | null
  rows_excluded: number | null
  notes: string[]
}

export type RetailMetrics = {
  columns_used: Record<MetricRole, string | null>
  number_rule: string
  row_count: MetricResult
  total_quantity: MetricResult
  total_revenue: MetricResult
  order_count: MetricResult
  average_order_value: MetricResult
}

export type CsvMetricsResponse = { filename: string; size_bytes: number; metrics: RetailMetrics }

export type Grain = 'day' | 'week' | 'month'

/** One period. Dates are calendar dates (YYYY-MM-DD); `end` is inclusive. */
export type TrendPeriod = { start: string; end: string; row_count: number }

/** A value per period. `value` is null when no row in the period could be used, never 0. */
export type TrendPoint = { value: number | null; rows_included: number }

export type TrendSeries = Omit<MetricResult, 'value'> & {
  /** One point per period, in the same order. Empty when the series is unavailable. */
  points: TrendPoint[]
}

export type SalesTrends = {
  grain: Grain
  columns_used: Record<MetricRole | 'order_date', string | null>
  date_rule: string
  number_rule: string
  dated_rows: MetricResult
  periods: TrendPeriod[]
  revenue: TrendSeries
  order_count: TrendSeries
  average_order_value: TrendSeries
}

export type CsvTrendsResponse = { filename: string; size_bytes: number; trends: SalesTrends }

export type PerformanceGroup = {
  label: string
  row_count: number
  /** null when no row of the group has a usable value, never 0. */
  revenue: number | null
  /** Percent of the breakdown's total revenue, rounded to 2 decimals. null when the total is not positive. */
  revenue_share: number | null
  quantity: number | null
  order_count: number | null
  /** Other labels that differ from this one only by letter case or spacing. Never merged. */
  similar_labels: string[]
  /** Products only: the categories its rows are filed under. */
  categories: string[]
  /** Categories only: distinct products among its rows (null without a product column). */
  product_count: number | null
}

/** Every group past the first 1,000, summarized so totals still add up. */
export type RemainingGroups = {
  group_count: number
  row_count: number
  revenue: number | null
  quantity: number | null
  order_count: number | null
}

export type Breakdown = {
  dimension: 'product' | 'category'
  status: 'calculated' | 'unavailable'
  definition: string
  columns_used: string[]
  rows_included: number | null
  rows_excluded: number | null
  notes: string[]
  ranked_by: 'revenue' | 'quantity' | 'row_count' | null
  group_count: number
  groups: PerformanceGroup[]
  remaining: RemainingGroups | null
  /** Totals over every labelled row (value), with each measure's definition and evidence. */
  revenue: MetricResult
  quantity: MetricResult
  order_count: MetricResult
}

export type ProductPerformance = {
  columns_used: Record<MetricRole | 'product' | 'category', string | null>
  label_rule: string
  number_rule: string
  products: Breakdown
  categories: Breakdown
}

export type CsvPerformanceResponse = { filename: string; size_bytes: number; performance: ProductPerformance }

// ---------- Requests ----------

export const UPLOAD_ENDPOINTS = {
  validate: '/api/uploads/csv',
  profile: '/api/uploads/csv/profile',
  metrics: '/api/uploads/csv/metrics',
  trends: '/api/uploads/csv/trends',
  performance: '/api/uploads/csv/performance',
} as const

/** Check that the file is a readable CSV. Returns its row count and column names. */
export function validateCsv(file: File, signal?: AbortSignal): Promise<CsvUploadResponse> {
  return requestJson(UPLOAD_ENDPOINTS.validate, csvForm(file, {}), isUploadResponse, signal)
}

/** Report missing values, duplicate rows, and inferred column types. */
export function profileCsv(file: File, signal?: AbortSignal): Promise<CsvProfileResponse> {
  return requestJson(UPLOAD_ENDPOINTS.profile, csvForm(file, {}), isProfileResponse, signal)
}

/** Calculate retail metrics. `mapping` holds explicit column choices; empty means automatic. */
export function calculateMetrics(file: File, mapping: ColumnMapping, signal?: AbortSignal): Promise<CsvMetricsResponse> {
  return requestJson(UPLOAD_ENDPOINTS.metrics, csvForm(file, mappingFormFields(mapping)), isMetricsResponse, signal)
}

/** Revenue, orders, and average order value per day, week, or month. */
export function calculateTrends(
  file: File,
  mapping: ColumnMapping,
  options: TrendOptions,
  signal?: AbortSignal,
): Promise<CsvTrendsResponse> {
  return requestJson(UPLOAD_ENDPOINTS.trends, csvForm(file, trendFormFields(mapping, options)), isTrendsResponse, signal)
}

/** Revenue, quantity, and orders by product and by category. */
export function calculatePerformance(
  file: File,
  mapping: ColumnMapping,
  options: PerformanceOptions,
  signal?: AbortSignal,
): Promise<CsvPerformanceResponse> {
  const form = csvForm(file, performanceFormFields(mapping, options))
  return requestJson(UPLOAD_ENDPOINTS.performance, form, isPerformanceResponse, signal)
}

/** A POST request carrying the file in the form field "file", plus any extra form fields. */
export function csvForm(file: File, fields: Record<string, string>): RequestInit {
  const form = new FormData()
  form.append('file', file, file.name)
  for (const [name, value] of Object.entries(fields)) form.append(name, value)
  return { method: 'POST', body: form }
}

// ---------- Response shape checks ----------
// FastAPI validates every response against its response_model, so these light checks
// only guard against a different program answering on the backend's port.

function isUploadResponse(value: unknown): value is CsvUploadResponse {
  return isObject(value) && typeof value.filename === 'string' && typeof value.row_count === 'number' && Array.isArray(value.columns)
}

function isProfileResponse(value: unknown): value is CsvProfileResponse {
  return isObject(value) && isObject(value.profile) && Array.isArray(value.profile.columns) && isObject(value.profile.definitions)
}

function isMetricsResponse(value: unknown): value is CsvMetricsResponse {
  return isObject(value) && isObject(value.metrics) && isObject(value.metrics.columns_used) && isObject(value.metrics.row_count)
}

function isTrendsResponse(value: unknown): value is CsvTrendsResponse {
  return isObject(value) && isObject(value.trends) && Array.isArray(value.trends.periods) && isObject(value.trends.revenue)
}

function isPerformanceResponse(value: unknown): value is CsvPerformanceResponse {
  return isObject(value) && isObject(value.performance) && isObject(value.performance.products) && isObject(value.performance.categories)
}
