import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  deleteDataset,
  getAnalysis,
  listAnalyses,
  listDatasets,
  runMetricsAnalysis,
  runPerformanceAnalysis,
  runProfileAnalysis,
  runTrendsAnalysis,
  saveDataset,
} from './datasets'
import { ApiError } from './http'

const file = new File(['order_id,quantity\nA1,2\n'], 'sales.csv', { type: 'text/csv' })

const DATASET = {
  id: 7,
  filename: 'sales.csv',
  size_bytes: 22,
  row_count: 1,
  column_count: 2,
  sha256: 'a'.repeat(64),
  created_at: '2026-10-11T09:12:00.000+00:00',
  analysis_count: 0,
  last_analyzed_at: null,
}
const DETAIL = { ...DATASET, columns: ['order_id', 'quantity'], file_stored: true }
const RECORD_BASE = { id: 3, dataset_id: 7, created_at: DATASET.created_at, app_version: '0.1.0', column_mapping: {} }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mockFetch(response: Response) {
  const fetchMock = vi.fn(async () => response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sentRequest(fetchMock: ReturnType<typeof mockFetch>) {
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
  return { url, init }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('requests match the backend contract', () => {
  it('lists datasets', async () => {
    const fetchMock = mockFetch(jsonResponse({ datasets: [DATASET] }))

    await expect(listDatasets()).resolves.toEqual([DATASET])
    expect(sentRequest(fetchMock).url).toBe('/api/datasets')
  })

  it('saves a file as multipart form data in the "file" field', async () => {
    const fetchMock = mockFetch(jsonResponse({ created: true, dataset: DETAIL }, 201))

    await expect(saveDataset(file)).resolves.toEqual({ created: true, dataset: DETAIL })

    const { url, init } = sentRequest(fetchMock)
    expect(url).toBe('/api/datasets')
    expect(init.method).toBe('POST')
    expect(((init.body as FormData).get('file') as File).name).toBe('sales.csv')
  })

  it('reports a duplicate upload as not created', async () => {
    mockFetch(jsonResponse({ created: false, dataset: DETAIL }, 200))

    const saved = await saveDataset(file)

    expect(saved.created).toBe(false)
    expect(saved.dataset.id).toBe(7)
  })

  it('sends DELETE and accepts an empty 204 response', async () => {
    const fetchMock = mockFetch(new Response(null, { status: 204 }))

    await expect(deleteDataset(7)).resolves.toBeUndefined()
    expect(sentRequest(fetchMock).url).toBe('/api/datasets/7')
    expect(sentRequest(fetchMock).init.method).toBe('DELETE')
  })

  it('runs a profile analysis with a JSON body', async () => {
    const fetchMock = mockFetch(jsonResponse({ ...RECORD_BASE, kind: 'profile', result: { columns: [] } }, 201))

    await runProfileAnalysis(7)

    const { url, init } = sentRequest(fetchMock)
    expect(url).toBe('/api/datasets/7/analyses')
    expect(init.method).toBe('POST')
    expect(new Headers(init.headers).get('Content-Type')).toBe('application/json')
    expect(JSON.parse(init.body as string)).toEqual({ kind: 'profile' })
  })

  it('sends only explicit column choices with a metrics analysis', async () => {
    const fetchMock = mockFetch(jsonResponse({ ...RECORD_BASE, kind: 'metrics', result: { row_count: {} } }, 201))

    await runMetricsAnalysis(7, { quantity: 'Qty', revenue: '' })

    expect(JSON.parse(sentRequest(fetchMock).init.body as string)).toEqual({
      kind: 'metrics',
      column_mapping: { quantity: 'Qty' },
    })
  })

  it('sends the grain and the column mapping, including the date column, with a trends analysis', async () => {
    const record = { ...RECORD_BASE, kind: 'trends', grain: 'week', result: { periods: [], revenue: {} } }
    const fetchMock = mockFetch(jsonResponse(record, 201))

    await expect(runTrendsAnalysis(7, { order_id: 'OrderNo', revenue: '' }, { grain: 'week', dateColumn: 'Day' })).resolves.toEqual(record)

    expect(JSON.parse(sentRequest(fetchMock).init.body as string)).toEqual({
      kind: 'trends',
      grain: 'week',
      column_mapping: { order_id: 'OrderNo', order_date: 'Day' },
    })
  })

  it('sends the product and category columns with a performance analysis', async () => {
    const record = { ...RECORD_BASE, kind: 'performance', result: { products: {}, categories: {} } }
    const fetchMock = mockFetch(jsonResponse(record, 201))

    await expect(runPerformanceAnalysis(7, { quantity: 'Qty' }, { productColumn: 'SKU', categoryColumn: 'Dept' })).resolves.toEqual(record)

    expect(JSON.parse(sentRequest(fetchMock).init.body as string)).toEqual({
      kind: 'performance',
      column_mapping: { quantity: 'Qty', product: 'SKU', category: 'Dept' },
    })
  })

  it('reads a recorded performance analysis from the history', async () => {
    const record = { ...RECORD_BASE, kind: 'performance', result: { products: {}, categories: {} } }
    mockFetch(jsonResponse(record))

    await expect(getAnalysis(7, 3)).resolves.toEqual(record)
  })

  it('reads a recorded trends analysis from the history', async () => {
    const record = { ...RECORD_BASE, kind: 'trends', grain: 'month', result: { periods: [], revenue: {} } }
    mockFetch(jsonResponse(record))

    await expect(getAnalysis(7, 3)).resolves.toEqual(record)
  })

  it('reads the history and one recorded analysis', async () => {
    const summary = { ...RECORD_BASE, kind: 'profile', highlights: { duplicate_row_count: 0, missing_value_count: 0, type_mismatch_count: 0 } }
    let fetchMock = mockFetch(jsonResponse({ analyses: [summary] }))
    await expect(listAnalyses(7)).resolves.toEqual([summary])
    expect(sentRequest(fetchMock).url).toBe('/api/datasets/7/analyses')

    vi.unstubAllGlobals()
    fetchMock = mockFetch(jsonResponse({ ...RECORD_BASE, kind: 'metrics', result: { row_count: {} } }))
    await getAnalysis(7, 3)
    expect(sentRequest(fetchMock).url).toBe('/api/datasets/7/analyses/3')
  })
})

describe('errors and unexpected answers', () => {
  it('shows the backend message for a missing dataset', async () => {
    mockFetch(jsonResponse({ detail: 'Dataset 99 was not found. It may have been deleted.' }, 404))

    const error = (await listAnalyses(99).catch((e: unknown) => e)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(404)
    expect(error.message).toBe('Dataset 99 was not found. It may have been deleted.')
  })

  it('rejects an analysis record of the wrong kind', async () => {
    mockFetch(jsonResponse({ ...RECORD_BASE, kind: 'metrics', result: {} }, 201))

    await expect(runProfileAnalysis(7)).rejects.toThrow('not InsightFlow data')
    mockFetch(jsonResponse({ ...RECORD_BASE, kind: 'metrics', result: {} }, 201))
    await expect(runTrendsAnalysis(7, {}, { grain: 'month', dateColumn: '' })).rejects.toThrow('not InsightFlow data')
    mockFetch(jsonResponse({ ...RECORD_BASE, kind: 'trends', grain: 'month', result: {} }, 201))
    await expect(runPerformanceAnalysis(7, {}, { productColumn: '', categoryColumn: '' })).rejects.toThrow('not InsightFlow data')
  })

  it('rejects a dataset list that is not InsightFlow data', async () => {
    mockFetch(jsonResponse({ datasets: [{ name: 'x' }] }))

    await expect(listDatasets()).rejects.toThrow('not InsightFlow data')
  })
})
