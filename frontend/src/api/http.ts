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

// ---------- Sending requests ----------

const TIMEOUT_MS = 120_000
const TIMEOUT_MESSAGE = 'The server did not answer within 2 minutes. Try again; large files take longer.'

/** Send a request and parse its JSON body, which must pass `isExpected`. */
export async function requestJson<T>(
  url: string,
  init: RequestInit,
  isExpected: (body: unknown) => body is T,
  signal?: AbortSignal,
): Promise<T> {
  const { response, timeout } = await send(url, init, signal)
  let body: unknown
  try {
    body = await response.json()
  } catch (error) {
    throw requestFailure(error, signal, timeout, 'The server sent a response that is not valid JSON.')
  }
  if (!isExpected(body)) {
    throw new ApiError(
      "The server's response is not InsightFlow data. Is another program using port 8000?",
      response.status,
    )
  }
  return body
}

/** Send a request whose success response has no body (HTTP 204). */
export async function requestNoContent(url: string, init: RequestInit, signal?: AbortSignal): Promise<void> {
  await send(url, init, signal)
}

async function send(url: string, init: RequestInit, signal?: AbortSignal) {
  const timeout = AbortSignal.timeout(TIMEOUT_MS)
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout
  let response: Response
  try {
    response = await fetch(url, { ...init, signal: combined })
  } catch (error) {
    throw requestFailure(error, signal, timeout, `Could not reach the backend. ${START_BACKEND_HINT}`)
  }
  if (!response.ok) throw await errorFromResponse(response)
  return { response, timeout }
}

/** Cancellation is passed through unchanged so callers can ignore it; anything else gets a clear message. */
function requestFailure(error: unknown, signal: AbortSignal | undefined, timeout: AbortSignal, message: string): unknown {
  if (signal?.aborted) return error
  if (timeout.aborted) return new ApiError(TIMEOUT_MESSAGE, null, { cause: error })
  return new ApiError(message, null, { cause: error })
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
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
