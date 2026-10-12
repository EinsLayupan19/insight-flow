// Shared helpers for calling the FastAPI backend. All calls go through `/api`, which the Vite dev
// server (see vite.config.ts) or, in production, the reverse proxy forwards to FastAPI.

// 502/503/504 come from the proxy when FastAPI is not answering (in development: nothing on port 8000).
export const GATEWAY_ERRORS = [502, 503, 504]
export const START_BACKEND_HINT =
  'Make sure the FastAPI server is running on port 8000 (see "Start the backend" in the README).'

// ---------- Messages ----------
// During development, messages point at the local setup (port 8000, the backend terminal). The production
// build names no ports, files, or internals; the details stay in the server's log.
// `import.meta.env.DEV` is read where it is used: the build replaces it with `false` and drops the development
// text from the bundle, and tests can switch it with vi.stubEnv.

/** The request never got an answer from FastAPI: no network (`status` null), or the proxy answered 502/503/504. */
export function unreachableMessage(status: number | null = null): string {
  const code = status === null ? '' : ` (HTTP ${status})`
  if (import.meta.env.DEV) return `Could not reach the backend${code}. ${START_BACKEND_HINT}`
  return status === null
    ? 'Could not reach InsightFlow. Check your internet connection, then try again.'
    : `InsightFlow's server is not answering right now${code}. Wait a minute, then try again.`
}

/** Something answered, but not with what InsightFlow sends. */
export function unexpectedResponseMessage(): string {
  return import.meta.env.DEV
    ? "The server's response is not InsightFlow data. Is another program using port 8000?"
    : 'The server sent an unexpected response. Reload the page, then try again.'
}

// Answers without a message from the API, typically from the reverse proxy (sign-in, size and rate limits).
const STATUS_MESSAGES: Record<number, string> = {
  401: 'You are not signed in, or the sign-in was not accepted. Reload the page to sign in again.',
  403: 'The server refused this request. Reload the page to sign in again.',
  404: 'The server could not find what was asked for. It may have been deleted; reload the page.',
  413: 'The file is larger than the server accepts.',
  429: 'Too many requests in a short time. Wait a moment, then try again.',
}

/** A failed answer that carries no message written for the user. Server errors never show their details. */
export function statusMessage(status: number): string {
  if (status < 500) {
    return STATUS_MESSAGES[status] ?? `The server did not accept the request (HTTP ${status}). Reload the page, then try again.`
  }
  return import.meta.env.DEV
    ? `The server could not complete the request (HTTP ${status}). Check the backend terminal for details.`
    : `The server could not complete the request (HTTP ${status}). Try again in a moment; if it keeps happening, check the server log.`
}

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
    return new ApiError(unreachableMessage(response.status), response.status)
  }

  // Client errors (4xx) from the API carry a message written for the user. Server errors (5xx)
  // are reported generically so internal details never reach the page.
  if (response.status < 500) {
    const detail = describeDetail(await response.json().catch(() => null))
    if (detail) return new ApiError(detail, response.status)
  }
  return new ApiError(statusMessage(response.status), response.status)
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
    const message = import.meta.env.DEV ? 'The server sent a response that is not valid JSON.' : unexpectedResponseMessage()
    throw requestFailure(error, signal, timeout, message)
  }
  if (!isExpected(body)) {
    throw new ApiError(unexpectedResponseMessage(), response.status)
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
    throw requestFailure(error, signal, timeout, unreachableMessage())
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
