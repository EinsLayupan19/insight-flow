// Calls the optional narrator endpoints in backend/app/api/narration.py. Narration only works on
// saved key findings; the server narrates findings it computed itself and checks the model's text.

import { isObject, requestJson } from './http'

export type NarratorStatus = {
  /** A narrator is configured on the server. */
  enabled: boolean
  provider: string | null
  model: string | null
  /** It answered a status check just now. */
  available: boolean
  /** Why it is unavailable, with the fix when there is one. */
  reason: string | null
}

export type NarrationRecord = {
  id: number
  dataset_id: number
  analysis_id: number
  created_at: string
  provider: string
  model: string
  prompt_version: string
  /** accepted: the model's text passed every check. rejected: it failed one. failed: the model did not answer. */
  status: 'accepted' | 'rejected' | 'failed'
  /** Whether `text` was written by the model or is the template summary. */
  source: 'ai' | 'template'
  /** What to show: the model's text only when status is accepted. Plain text. */
  text: string
  problems: string[]
}

const narrationsUrl = (datasetId: number, analysisId: number) => `/api/datasets/${datasetId}/analyses/${analysisId}/narrations`

export function getNarratorStatus(signal?: AbortSignal): Promise<NarratorStatus> {
  return requestJson('/api/insights/narrator', {}, isNarratorStatus, signal)
}

/** Recorded summaries of a saved analysis, newest first. */
export async function listNarrations(datasetId: number, analysisId: number, signal?: AbortSignal): Promise<NarrationRecord[]> {
  const body = await requestJson(narrationsUrl(datasetId, analysisId), {}, isNarrationList, signal)
  return body.narrations
}

/** Ask the local narrator for a summary. It can take a minute on a laptop CPU. */
export function createNarration(datasetId: number, analysisId: number, signal?: AbortSignal): Promise<NarrationRecord> {
  return requestJson(narrationsUrl(datasetId, analysisId), { method: 'POST' }, isNarrationRecord, signal)
}

function isNarratorStatus(value: unknown): value is NarratorStatus {
  return isObject(value) && typeof value.enabled === 'boolean' && typeof value.available === 'boolean'
}

function isNarrationRecord(value: unknown): value is NarrationRecord {
  return isObject(value) && typeof value.id === 'number' && typeof value.text === 'string' && Array.isArray(value.problems)
}

function isNarrationList(value: unknown): value is { narrations: NarrationRecord[] } {
  return isObject(value) && Array.isArray(value.narrations) && value.narrations.every(isNarrationRecord)
}
