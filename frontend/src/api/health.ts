// Talks to the backend health endpoint. All calls go through `/api`,
// which the Vite dev server forwards to FastAPI (see vite.config.ts).

import { GATEWAY_ERRORS, START_BACKEND_HINT } from './http'

export type HealthResponse = {
  status: 'ok'
  app_name: string
  version: string
  environment: string
}

const HEALTH_URL = '/api/health'
const TIMEOUT_MS = 5000

export async function fetchHealth(): Promise<HealthResponse> {
  let response: Response
  try {
    response = await fetch(HEALTH_URL, { signal: AbortSignal.timeout(TIMEOUT_MS) })
  } catch (error) {
    throw new Error(`Could not reach the backend. ${START_BACKEND_HINT}`, { cause: error })
  }

  if (GATEWAY_ERRORS.includes(response.status)) {
    throw new Error(`Could not reach the backend (HTTP ${response.status}). ${START_BACKEND_HINT}`)
  }
  if (!response.ok) {
    throw new Error(`The backend responded with an error (HTTP ${response.status}). Check the backend terminal for details.`)
  }

  const body: unknown = await response.json().catch(() => null)
  if (!isHealthResponse(body)) {
    throw new Error(
      'Something answered on /api/health, but not with InsightFlow health data. Is another program using port 8000?',
    )
  }
  return body
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== 'object' || value === null) return false
  const v = value as Record<string, unknown>
  return (
    v.status === 'ok' &&
    typeof v.app_name === 'string' &&
    typeof v.version === 'string' &&
    typeof v.environment === 'string'
  )
}
