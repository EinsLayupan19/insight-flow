import { describe, expect, it } from 'vitest'
import { failedFrom, latestData, loadingFrom, type RequestState } from './requestState'

describe('request state helpers', () => {
  const loaded: RequestState<string> = { status: 'success', data: 'report' }

  it('keeps the last result visible while reloading and after a failed reload', () => {
    const reloading = loadingFrom(loaded)
    expect(reloading).toEqual({ status: 'loading', previous: 'report' })
    expect(latestData(reloading)).toBe('report')

    const failed = failedFrom(reloading, 'Network down')
    expect(failed).toEqual({ status: 'error', message: 'Network down', previous: 'report' })
    expect(latestData(failed)).toBe('report')
  })

  it('has no data before anything loaded', () => {
    expect(latestData({ status: 'idle' })).toBeNull()
    expect(latestData(loadingFrom<string>({ status: 'idle' }))).toBeNull()
  })
})
