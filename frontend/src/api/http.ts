// Shared helpers for calling the FastAPI backend. All calls go through `/api`,
// which the Vite dev server forwards to FastAPI (see vite.config.ts).

// 502/503/504 come from the Vite proxy when nothing is listening on port 8000.
export const GATEWAY_ERRORS = [502, 503, 504]
export const START_BACKEND_HINT =
  'Make sure the FastAPI server is running on port 8000 (see "Start the backend" in the README).'

/** A failed request. `message` is written for the person using the app. */
export class ApiError extends Error {
  readonly status: number | null

  constructor(message: string, status: number | null = null, options?: ErrorOptions) {
    super(message, options)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Turn a non-2xx response into an ApiError with the clearest message available. */
export async function errorFromResponse(response: Response): Promise<ApiError> {
  if (GATEWAY_ERRORS.includes(response.status)) {
    return new ApiError(`Could not reach the backend (HTTP ${response.status}). ${START_BACKEND_HINT}`, response.status)
  }

  // Client errors (4xx) carry a message written for the user. Server errors (5xx)
  // are reported generically so internal details never reach the page.
  if (response.status < 500) {
    const detail = describeDetail(await response.json().catch(() => null))
    if (detail) return new ApiError(detail, response.status)
  }
  return new ApiError(
    `The server could not complete the request (HTTP ${response.status}). Check the backend terminal for details.`,
    response.status,
  )
}

/** FastAPI errors look like {"detail": "message"} or {"detail": [{"msg": "..."}, ...]}. */
export function describeDetail(body: unknown): string | null {
  if (typeof body !== 'object' || body === null || !('detail' in body)) return null
  const { detail } = body as { detail: unknown }

  if (typeof detail === 'string') return detail.trim() || null
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: unknown) => (typeof item === 'object' && item !== null ? (item as { msg?: unknown }).msg : null))
      .filter((msg): msg is string => typeof msg === 'string' && msg.length > 0)
    if (messages.length > 0) return `The request was not accepted: ${messages.join('; ')}.`
  }
  return null
}
