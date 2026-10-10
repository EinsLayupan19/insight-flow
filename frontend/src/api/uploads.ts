// Calls the CSV analysis endpoints in backend/app/api/uploads.py. Each call sends the
// file as multipart form data in the field named "file". The backend reads the file
// in memory, analyzes it, and discards it: nothing is stored between requests, so
// every analysis step uploads the file again.

import { mappingFormFields, type ColumnMapping, type MetricRole } from '../lib/columnMapping'
import { ApiError, START_BACKEND_HINT, errorFromResponse } from './http'

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

// ---------- Requests ----------

export const UPLOAD_ENDPOINTS = {
  validate: '/api/uploads/csv',
  profile: '/api/uploads/csv/profile',
  metrics: '/api/uploads/csv/metrics',
} as const

const TIMEOUT_MS = 120_000
const TIMEOUT_MESSAGE = 'The server did not answer within 2 minutes. Try again, or try a smaller file.'

/** Check that the file is a readable CSV. Returns its row count and column names. */
export function validateCsv(file: File, signal?: AbortSignal): Promise<CsvUploadResponse> {
  return postCsv(UPLOAD_ENDPOINTS.validate, file, {}, signal, isUploadResponse)
}

/** Report missing values, duplicate rows, and inferred column types. */
export function profileCsv(file: File, signal?: AbortSignal): Promise<CsvProfileResponse> {
  return postCsv(UPLOAD_ENDPOINTS.profile, file, {}, signal, isProfileResponse)
}

/** Calculate retail metrics. `mapping` holds explicit column choices; empty means automatic. */
export function calculateMetrics(file: File, mapping: ColumnMapping, signal?: AbortSignal): Promise<CsvMetricsResponse> {
  return postCsv(UPLOAD_ENDPOINTS.metrics, file, mappingFormFields(mapping), signal, isMetricsResponse)
}

async function postCsv<T>(
  url: string,
  file: File,
  fields: Record<string, string>,
  signal: AbortSignal | undefined,
  isExpected: (body: unknown) => body is T,
): Promise<T> {
  const form = new FormData()
  form.append('file', file, file.name)
  for (const [name, value] of Object.entries(fields)) form.append(name, value)

  const timeout = AbortSignal.timeout(TIMEOUT_MS)
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout

  let response: Response
  try {
    response = await fetch(url, { method: 'POST', body: form, signal: combined })
  } catch (error) {
    throw requestFailure(error, signal, timeout, `Could not reach the backend. ${START_BACKEND_HINT}`)
  }
  if (!response.ok) throw await errorFromResponse(response)

  let body: unknown
  try {
    body = await response.json()
  } catch (error) {
    throw requestFailure(error, signal, timeout, 'The server sent a response that is not valid JSON.')
  }
  if (!isExpected(body)) {
    throw new ApiError(
      "The server's response is not InsightFlow analysis data. Is another program using port 8000?",
      response.status,
    )
  }
  return body
}

/** Cancellation is passed through unchanged so callers can ignore it; anything else gets a clear message. */
function requestFailure(error: unknown, signal: AbortSignal | undefined, timeout: AbortSignal, message: string): unknown {
  if (signal?.aborted) return error
  if (timeout.aborted) return new ApiError(TIMEOUT_MESSAGE, null, { cause: error })
  return new ApiError(message, null, { cause: error })
}

// ---------- Response shape checks ----------
// FastAPI validates every response against its response_model, so these light checks
// only guard against a different program answering on the backend's port.

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isUploadResponse(value: unknown): value is CsvUploadResponse {
  return isObject(value) && typeof value.filename === 'string' && typeof value.row_count === 'number' && Array.isArray(value.columns)
}

function isProfileResponse(value: unknown): value is CsvProfileResponse {
  return isObject(value) && isObject(value.profile) && Array.isArray(value.profile.columns) && isObject(value.profile.definitions)
}

function isMetricsResponse(value: unknown): value is CsvMetricsResponse {
  return isObject(value) && isObject(value.metrics) && isObject(value.metrics.columns_used) && isObject(value.metrics.row_count)
}
