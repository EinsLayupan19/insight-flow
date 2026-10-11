// Calls the dataset library endpoints in backend/app/api/datasets.py.
//
// Unlike the in-memory upload endpoints, saving a dataset keeps the file: the server
// stores it on its own disk and keeps its metadata and every analysis in SQLite,
// until the dataset is deleted.

import { explicitMapping, type ColumnMapping } from '../lib/columnMapping'
import { isObject, requestJson, requestNoContent } from './http'
import { csvForm, type QualityReport, type RetailMetrics } from './uploads'

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

type AnalysisBase = {
  id: number
  dataset_id: number
  created_at: string
  app_version: string
  column_mapping: ColumnMapping
}

export type AnalysisSummary = AnalysisBase &
  ({ kind: 'profile'; highlights: ProfileHighlights } | { kind: 'metrics'; highlights: MetricsHighlights })

export type ProfileAnalysisRecord = AnalysisBase & { kind: 'profile'; result: QualityReport }
export type MetricsAnalysisRecord = AnalysisBase & { kind: 'metrics'; result: RetailMetrics }
export type AnalysisRecord = ProfileAnalysisRecord | MetricsAnalysisRecord

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
  return isObject(value) && typeof value.id === 'number' && (value.kind === 'profile' || value.kind === 'metrics') && isObject(value.result)
}

function isProfileRecord(value: unknown): value is ProfileAnalysisRecord {
  return isAnalysisRecord(value) && value.kind === 'profile'
}

function isMetricsRecord(value: unknown): value is MetricsAnalysisRecord {
  return isAnalysisRecord(value) && value.kind === 'metrics'
}
