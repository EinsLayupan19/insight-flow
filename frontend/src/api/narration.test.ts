import { afterEach, describe, expect, it, vi } from 'vitest'
import { createNarration, getNarratorStatus, listNarrations } from './narration'

const STATUS = { enabled: false, provider: null, model: null, available: false, reason: 'No narrator is configured.' }
const RECORD = {
  id: 1,
  dataset_id: 7,
  analysis_id: 3,
  created_at: '2026-10-12T09:00:00.000+00:00',
  provider: 'ollama',
  model: 'llama3.2:3b',
  prompt_version: 'narration-v1',
  status: 'accepted',
  source: 'ai',
  text: 'Revenue was 120.00 in March 2026.',
  problems: [],
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mockFetch(response: Response) {
  const fetchMock = vi.fn(async () => response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sent(fetchMock: ReturnType<typeof mockFetch>) {
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
  return { url, init }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('narration requests', () => {
  it('reads the narrator status', async () => {
    const fetchMock = mockFetch(jsonResponse(STATUS))

    await expect(getNarratorStatus()).resolves.toEqual(STATUS)
    expect(sent(fetchMock).url).toBe('/api/insights/narrator')
  })

  it('lists and creates narrations of a saved analysis', async () => {
    let fetchMock = mockFetch(jsonResponse({ narrations: [RECORD] }))
    await expect(listNarrations(7, 3)).resolves.toEqual([RECORD])
    expect(sent(fetchMock).url).toBe('/api/datasets/7/analyses/3/narrations')

    vi.unstubAllGlobals()
    fetchMock = mockFetch(jsonResponse(RECORD, 201))
    await expect(createNarration(7, 3)).resolves.toEqual(RECORD)
    expect(sent(fetchMock).init.method).toBe('POST')
  })

  it('shows the backend reason when no narrator is configured', async () => {
    mockFetch(jsonResponse({ detail: 'No narrator is configured. Set INSIGHTS_NARRATOR=ollama.' }, 409))

    await expect(createNarration(7, 3)).rejects.toThrow('No narrator is configured')
  })

  it('rejects answers that are not InsightFlow data', async () => {
    mockFetch(jsonResponse({ narrations: [{ hello: 'world' }] }))

    await expect(listNarrations(7, 3)).rejects.toThrow('not InsightFlow data')
  })
})
