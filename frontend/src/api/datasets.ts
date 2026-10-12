// Calls the dataset library endpoints in backend/app/api/datasets.py.
//
// Unlike the in-memory upload endpoints, saving a dataset keeps the file: the server
// stores it on its own disk and keeps its metadata and every analysis in SQLite,
// until the dataset is deleted.

import { explicitMapping, type ColumnMapping, type RecordedColumnMapping } from '../lib/columnMapping'
import { insightColumnMapping, type InsightOptions } from '../lib/insights'
import { performanceColumnMapping, type PerformanceOptions } from '../lib/performance'
import { trendColumnMapping, type TrendOptions } from '../lib/trends'
import { isObject, requestJson, requestNoContent } from './http'
import {
  csvForm,
  type Grain,
  type ProductPerformance,
  type QualityReport,
  type RetailMetrics,
  type SalesInsights,
  type SalesTrends,
} from './uploads'

// ---------- Response types (mirror backend/app/datasets/models.py) ----------

export type DatasetSummary = {
  id: number
  filename: string
  size_bytes: number
  row_count: number
  column_count: number
  sha256: string
  created_at: string
  analysis_count: number
  last_analyzed_at: string | null
}

export type DatasetDetail = DatasetSummary & {
  columns: string[]
  /** The stored copy of the file is on the server's disk with the expected size. */
  file_stored: boolean
}

export type SaveDatasetResponse = {
  /** False when the same content was already saved: nothing new was stored. */
  created: boolean
  dataset: DatasetDetail
}

export type ProfileHighlights = { duplicate_row_count: number; missing_value_count: number; type_mismatch_count: number }
export type MetricsHighlights = { calculated_count: number; unavailable_count: number }
/** calculated_count and unavailable_count are out of the three trends: revenue, orders, average order value. */
export type TrendsHighlights = { grain: Grain; period_count: number; calculated_count: number; unavailable_count: number }

/** null when that breakdown is unavailable (for example, the file has no category column). */
export type PerformanceHighlights = { product_count: number | null; category_count: number | null }

export type InsightsHighlights = { grain: Grain; finding_count: number; high_count: number; not_assessed_count: number }

export type AnalysisKind = 'profile' | 'metrics' | 'trends' | 'performance' | 'insights'
const ANALYSIS_KINDS: readonly unknown[] = ['profile', 'metrics', 'trends', 'performance', 'insights'] satisfies AnalysisKind[]

type AnalysisBase = {
  id: number
  dataset_id: number
  created_at: string
  app_version: string
  /** Explicit column choices. order_date appears for trends and insights; product and category for performance and insights. */
  column_mapping: RecordedColumnMapping
}

export type AnalysisSummary = AnalysisBase &
  (
    | { kind: 'profile'; highlights: ProfileHighlights }
    | { kind: 'metrics'; highlights: MetricsHighlights }
    | { kind: 'trends'; highlights: TrendsHighlights }
    | { kind: 'performance'; highlights: PerformanceHighlights }
    | { kind: 'insights'; highlights: InsightsHighlights }
  )

export type ProfileAnalysisRecord = AnalysisBase & { kind: 'profile'; result: QualityReport }
export type MetricsAnalysisRecord = AnalysisBase & { kind: 'metrics'; result: RetailMetrics }
export type TrendsAnalysisRecord = AnalysisBase & { kind: 'trends'; grain: Grain; result: SalesTrends }
export type PerformanceAnalysisRecord = AnalysisBase & { kind: 'performance'; result: ProductPerformance }
export type InsightsAnalysisRecord = AnalysisBase & { kind: 'insights'; grain: Grain; result: SalesInsights }
export type AnalysisRecord =
  | ProfileAnalysisRecord
  | MetricsAnalysisRecord
  | TrendsAnalysisRecord
  | PerformanceAnalysisRecord
  | InsightsAnalysisRecord

// ---------- Requests ----------

export const DATASETS_URL = '/api/datasets'

const datasetUrl = (datasetId: number) => `${DATASETS_URL}/${datasetId}`
const analysesUrl = (datasetId: number) => `${datasetUrl(datasetId)}/analyses`

/** Saved datasets, newest first. */
export async function listDatasets(signal?: AbortSignal): Promise<DatasetSummary[]> {
  const body = await requestJson(DATASETS_URL, {}, isDatasetList, signal)
  return body.datasets
}

export function getDataset(datasetId: number, signal?: AbortSignal): Promise<DatasetDetail> {
  return requestJson(datasetUrl(datasetId), {}, isDatasetDetail, signal)
}

/** Validate and store a CSV. Identical content returns the existing dataset with created=false. */
export function saveDataset(file: File, signal?: AbortSignal): Promise<SaveDatasetResponse> {
  return requestJson(DATASETS_URL, csvForm(file, {}), isSaveResponse, signal)
}

/** Delete the stored file, the metadata, and the analysis history. */
export function deleteDataset(datasetId: number, signal?: AbortSignal): Promise<void> {
  return requestNoContent(datasetUrl(datasetId), { method: 'DELETE' }, signal)
}

/** A dataset's analysis history, newest first. */
export async function listAnalyses(datasetId: number, signal?: AbortSignal): Promise<AnalysisSummary[]> {
  const body = await requestJson(analysesUrl(datasetId), {}, isAnalysisList, signal)
  return body.analyses
}

export function getAnalysis(datasetId: number, analysisId: number, signal?: AbortSignal): Promise<AnalysisRecord> {
  return requestJson(`${analysesUrl(datasetId)}/${analysisId}`, {}, isAnalysisRecord, signal)
}

/** Run a data-quality check on the stored file and record it in the history. */
export function runProfileAnalysis(datasetId: number, signal?: AbortSignal): Promise<ProfileAnalysisRecord> {
  return requestJson(analysesUrl(datasetId), jsonPost({ kind: 'profile' }), isProfileRecord, signal)
}

/** Calculate retail metrics on the stored file and record them. Only explicit column choices are sent. */
export function runMetricsAnalysis(
  datasetId: number,
  mapping: ColumnMapping,
  signal?: AbortSignal,
): Promise<MetricsAnalysisRecord> {
  const body = { kind: 'metrics', column_mapping: explicitMapping(mapping) }
  return requestJson(analysesUrl(datasetId), jsonPost(body), isMetricsRecord, signal)
}

/** Calculate sales trends on the stored file and record them. Only explicit column choices are sent. */
export function runTrendsAnalysis(
  datasetId: number,
  mapping: ColumnMapping,
  options: TrendOptions,
  signal?: AbortSignal,
): Promise<TrendsAnalysisRecord> {
  const body = { kind: 'trends', grain: options.grain, column_mapping: trendColumnMapping(mapping, options) }
  return requestJson(analysesUrl(datasetId), jsonPost(body), isTrendsRecord, signal)
}

/** Rank products and categories in the stored file and record it. Only explicit column choices are sent. */
export function runPerformanceAnalysis(
  datasetId: number,
  mapping: ColumnMapping,
  options: PerformanceOptions,
  signal?: AbortSignal,
): Promise<PerformanceAnalysisRecord> {
  const body = { kind: 'performance', column_mapping: performanceColumnMapping(mapping, options) }
  return requestJson(analysesUrl(datasetId), jsonPost(body), isPerformanceRecord, signal)
}

/** Find key insights in the stored file and record them. Only explicit column choices are sent. */
export function runInsightsAnalysis(
  datasetId: number,
  mapping: ColumnMapping,
  options: InsightOptions,
  signal?: AbortSignal,
): Promise<InsightsAnalysisRecord> {
  const body = { kind: 'insights', grain: options.grain, column_mapping: insightColumnMapping(mapping, options) }
  return requestJson(analysesUrl(datasetId), jsonPost(body), isInsightsRecord, signal)
}

function jsonPost(body: unknown): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

// ---------- Response shape checks ----------
// FastAPI validates every response against its response_model, so these light checks
// only guard against a different program answering on the backend's port.

function isDatasetSummary(value: unknown): value is DatasetSummary {
  return isObject(value) && typeof value.id === 'number' && typeof value.filename === 'string' && typeof value.sha256 === 'string'
}

function isDatasetDetail(value: unknown): value is DatasetDetail {
  return isObject(value) && Array.isArray(value.columns) && typeof value.file_stored === 'boolean' && isDatasetSummary(value)
}

function isDatasetList(value: unknown): value is { datasets: DatasetSummary[] } {
  return isObject(value) && Array.isArray(value.datasets) && value.datasets.every(isDatasetSummary)
}

function isSaveResponse(value: unknown): value is SaveDatasetResponse {
  return isObject(value) && typeof value.created === 'boolean' && isDatasetDetail(value.dataset)
}

function isAnalysisList(value: unknown): value is { analyses: AnalysisSummary[] } {
  return (
    isObject(value) &&
    Array.isArray(value.analyses) &&
    value.analyses.every((entry) => isObject(entry) && typeof entry.id === 'number' && isObject(entry.highlights))
  )
}

function isAnalysisRecord(value: unknown): value is AnalysisRecord {
  return isObject(value) && typeof value.id === 'number' && ANALYSIS_KINDS.includes(value.kind) && isObject(value.result)
}

function isProfileRecord(value: unknown): value is ProfileAnalysisRecord {
  return isAnalysisRecord(value) && value.kind === 'profile'
}

function isMetricsRecord(value: unknown): value is MetricsAnalysisRecord {
  return isAnalysisRecord(value) && value.kind === 'metrics'
}

function isTrendsRecord(value: unknown): value is TrendsAnalysisRecord {
  return isAnalysisRecord(value) && value.kind === 'trends'
}

function isPerformanceRecord(value: unknown): value is PerformanceAnalysisRecord {
  return isAnalysisRecord(value) && value.kind === 'performance'
}

function isInsightsRecord(value: unknown): value is InsightsAnalysisRecord {
  return isAnalysisRecord(value) && value.kind === 'insights'
}
