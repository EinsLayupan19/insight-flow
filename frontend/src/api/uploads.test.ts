import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, describeDetail } from './http'
import { calculateMetrics, profileCsv, validateCsv } from './uploads'

const file = new File(['order_id,quantity\nA1,2\n'], 'sales.csv', { type: 'text/csv' })

const UPLOAD_OK = { filename: 'sales.csv', size_bytes: 22, row_count: 1, column_count: 2, columns: ['order_id', 'quantity'] }
const PROFILE_OK = { filename: 'sales.csv', size_bytes: 22, profile: { row_count: 1, columns: [], definitions: {} } }
const METRICS_OK = { filename: 'sales.csv', size_bytes: 22, metrics: { columns_used: {}, row_count: {} } }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mockFetch(response: Response | Error) {
  const fetchMock = vi.fn(async () => {
    if (response instanceof Error) throw response
    return response
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** The URL and form data of the first call to the mocked fetch. */
function sentRequest(fetchMock: ReturnType<typeof mockFetch>) {
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
  return { url, method: init.method, form: init.body as FormData }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('requests match the backend contract', () => {
  it('posts the file in the "file" field to the validation endpoint', async () => {
    const fetchMock = mockFetch(jsonResponse(UPLOAD_OK))

    await expect(validateCsv(file)).resolves.toEqual(UPLOAD_OK)

    const { url, method, form } = sentRequest(fetchMock)
    expect(url).toBe('/api/uploads/csv')
    expect(method).toBe('POST')
    expect((form.get('file') as File).name).toBe('sales.csv')
  })

  it('posts to the profile endpoint', async () => {
    const fetchMock = mockFetch(jsonResponse(PROFILE_OK))

    await profileCsv(file)

    expect(sentRequest(fetchMock).url).toBe('/api/uploads/csv/profile')
  })

  it('sends only explicit column choices to the metrics endpoint', async () => {
    const fetchMock = mockFetch(jsonResponse(METRICS_OK))

    await calculateMetrics(file, { order_id: 'OrderNo', quantity: 'Qty' })

    const { url, form } = sentRequest(fetchMock)
    expect(url).toBe('/api/uploads/csv/metrics')
    expect(form.get('order_id_column')).toBe('OrderNo')
    expect(form.get('quantity_column')).toBe('Qty')
    expect(form.has('unit_price_column')).toBe(false)
    expect(form.has('revenue_column')).toBe(false)
  })
})

describe('errors are explained, not hidden', () => {
  it('shows the backend message for a rejected file', async () => {
    mockFetch(jsonResponse({ detail: 'Line 3 has 1 values, but the header has 2 columns.' }, 422))

    const error = await validateCsv(file).catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe('Line 3 has 1 values, but the header has 2 columns.')
    expect((error as ApiError).status).toBe(422)
  })

  it('says the backend is unreachable when the proxy answers 502', async () => {
    mockFetch(new Response('Bad Gateway', { status: 502 }))

    await expect(validateCsv(file)).rejects.toThrow('Could not reach the backend (HTTP 502)')
  })

  it('does not show server error details from a 500 response', async () => {
    mockFetch(jsonResponse({ detail: 'Traceback: secret internals' }, 500))

    const error = (await validateCsv(file).catch((e: unknown) => e)) as ApiError

    expect(error.message).toContain('HTTP 500')
    expect(error.message).not.toContain('secret')
  })

  it('explains a network failure', async () => {
    mockFetch(new TypeError('Failed to fetch'))

    await expect(profileCsv(file)).rejects.toThrow('Could not reach the backend.')
  })

  it('rejects a response that is not InsightFlow data', async () => {
    mockFetch(jsonResponse({ hello: 'world' }))

    await expect(calculateMetrics(file, {})).rejects.toThrow('not InsightFlow analysis data')
  })

  it('passes a user cancellation through unchanged so it can be ignored', async () => {
    const controller = new AbortController()
    controller.abort()
    mockFetch(new DOMException('The operation was aborted.', 'AbortError'))

    const error = await validateCsv(file, controller.signal).catch((e: unknown) => e)

    expect(error).not.toBeInstanceOf(ApiError)
    expect((error as DOMException).name).toBe('AbortError')
  })
})

describe('describeDetail', () => {
  it('reads FastAPI error bodies', () => {
    expect(describeDetail({ detail: 'The file is empty.' })).toBe('The file is empty.')
    expect(describeDetail({ detail: [{ msg: 'Field required' }, { msg: 'Too long' }] })).toBe(
      'The request was not accepted: Field required; Too long.',
    )
    expect(describeDetail({ detail: '   ' })).toBeNull()
    expect(describeDetail('Internal Server Error')).toBeNull()
    expect(describeDetail(null)).toBeNull()
  })
})
