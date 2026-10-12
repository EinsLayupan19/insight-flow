import { afterEach, describe, expect, it, vi } from 'vitest'
import { userMessage } from '../lib/errors'
import { fetchHealth } from './health'
import { ApiError, isObject, requestJson } from './http'

// Words that only make sense on the developer's computer, or that would reveal internals.
const LOCAL_SETUP = /8000|README|terminal|console|Traceback|\/srv|secret/i

function respond(body: string, status: number, contentType = 'application/json') {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status, headers: { 'Content-Type': contentType } })))
}

function failNetwork() {
  vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
}

const isExpected = (body: unknown): body is { ok: true } => isObject(body) && body.ok === true

async function failure(): Promise<ApiError> {
  const error = await requestJson('/api/anything', {}, isExpected).catch((e: unknown) => e)
  expect(error).toBeInstanceOf(ApiError)
  return error as ApiError
}

function inProduction() {
  vi.stubEnv('DEV', false)
  vi.stubEnv('PROD', true)
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
})

describe('messages in the production build', () => {
  it('says the server is not answering when the reverse proxy cannot reach it', async () => {
    inProduction()
    respond('<html>502 Bad Gateway</html>', 502, 'text/html')

    const error = await failure()

    expect(error.message).toBe("InsightFlow's server is not answering right now (HTTP 502). Wait a minute, then try again.")
    expect(error.status).toBe(502)
  })

  it('points at the connection when the request never left the browser', async () => {
    inProduction()
    failNetwork()

    expect((await failure()).message).toBe('Could not reach InsightFlow. Check your internet connection, then try again.')
  })

  it('never shows the details of a server error', async () => {
    inProduction()
    respond(JSON.stringify({ detail: 'Traceback: /srv/insightflow/app.py secret' }), 500)

    const { message } = await failure()

    expect(message).toBe(
      'The server could not complete the request (HTTP 500). Try again in a moment; if it keeps happening, check the server log.',
    )
    expect(message).not.toMatch(LOCAL_SETUP)
  })

  it.each([
    [401, '<html>401 Authorization Required</html>', 'You are not signed in, or the sign-in was not accepted. Reload the page to sign in again.'],
    [413, '<html>413 Request Entity Too Large</html>', 'The file is larger than the server accepts.'],
    [429, '<html>429 Too Many Requests</html>', 'Too many requests in a short time. Wait a moment, then try again.'],
    [400, 'Invalid host header', 'The server did not accept the request (HTTP 400). Reload the page, then try again.'],
  ])('explains a %i answered by the reverse proxy without a JSON message', async (status, body, expected) => {
    inProduction()
    respond(body, status, 'text/html')

    expect((await failure()).message).toBe(expected)
  })

  it("still shows the API's own message for a rejected file", async () => {
    inProduction()
    respond(JSON.stringify({ detail: 'Line 3 has 1 values, but the header has 2 columns.' }), 422)

    expect((await failure()).message).toBe('Line 3 has 1 values, but the header has 2 columns.')
  })

  it('calls an answer that is not InsightFlow data unexpected, without guessing about ports', async () => {
    inProduction()
    respond('<html>sign in</html>', 200, 'text/html')
    const notJson = await failure()
    respond(JSON.stringify({ hello: 'world' }), 200)
    const wrongShape = await failure()

    for (const { message } of [notJson, wrongShape]) {
      expect(message).toBe('The server sent an unexpected response. Reload the page, then try again.')
    }
  })

  it('reports the health check without local setup hints', async () => {
    inProduction()
    respond('', 503, 'text/html')
    await expect(fetchHealth()).rejects.toThrow("InsightFlow's server is not answering right now (HTTP 503).")
    failNetwork()
    await expect(fetchHealth()).rejects.toThrow('Could not reach InsightFlow.')
    respond('{}', 200)
    await expect(fetchHealth()).rejects.toThrow('The server sent an unexpected response.')
  })

  it('does not log or mention the console for an unexpected app error', () => {
    inProduction()
    const log = vi.spyOn(console, 'error').mockImplementation(() => {})

    expect(userMessage(new Error('internal state'))).toBe('Something went wrong in the app. Reload the page, then try again.')
    expect(log).not.toHaveBeenCalled()
  })
})

describe('messages during development', () => {
  it('names the local backend that is not running', async () => {
    respond('Bad Gateway', 502, 'text/plain')

    expect((await failure()).message).toBe(
      'Could not reach the backend (HTTP 502). Make sure the FastAPI server is running on port 8000 (see "Start the backend" in the README).',
    )
  })

  it('points at the backend terminal for a server error, still without its details', async () => {
    respond(JSON.stringify({ detail: 'Traceback: secret' }), 500)

    const { message } = await failure()

    expect(message).toBe('The server could not complete the request (HTTP 500). Check the backend terminal for details.')
    expect(message).not.toContain('secret')
  })

  it('logs an unexpected app error to the browser console', () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {})

    expect(userMessage(new Error('internal state'))).toContain('check the browser console')
    expect(log).toHaveBeenCalledOnce()
  })
})
