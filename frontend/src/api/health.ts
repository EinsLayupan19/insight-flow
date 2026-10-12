// Talks to the backend health endpoint. All calls go through `/api`, which the Vite dev
// server (see vite.config.ts) or, in production, the reverse proxy forwards to FastAPI.

import { GATEWAY_ERRORS, statusMessage, unexpectedResponseMessage, unreachableMessage } from './http'

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
    throw new Error(unreachableMessage(), { cause: error })
  }

  if (GATEWAY_ERRORS.includes(response.status)) throw new Error(unreachableMessage(response.status))
  if (!response.ok) throw new Error(statusMessage(response.status))

  const body: unknown = await response.json().catch(() => null)
  if (!isHealthResponse(body)) throw new Error(unexpectedResponseMessage())
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
