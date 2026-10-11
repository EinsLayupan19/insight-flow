import { describe, expect, it } from 'vitest'
import { datasetHref, parseRoute, routeHref, type Route } from './route'

describe('parseRoute', () => {
  it('opens the Analyze page for an empty or unknown hash', () => {
    for (const hash of ['', '#', '#/', '#data-quality', '#/settings', '#/datasets/abc']) {
      expect(parseRoute(hash)).toEqual({ page: 'analyze' })
    }
  })

  it('reads the dataset list, a dataset, and one of its analyses', () => {
    expect(parseRoute('#/datasets')).toEqual({ page: 'datasets' })
    expect(parseRoute('#/datasets/')).toEqual({ page: 'datasets' })
    expect(parseRoute('#/datasets/12')).toEqual({ page: 'dataset', datasetId: 12, analysisId: null })
    expect(parseRoute('#/datasets/12/analyses/5')).toEqual({ page: 'dataset', datasetId: 12, analysisId: 5 })
  })

  it('rejects ids that cannot exist', () => {
    expect(parseRoute('#/datasets/0')).toEqual({ page: 'analyze' })
    expect(parseRoute('#/datasets/12/analyses/-1')).toEqual({ page: 'analyze' })
  })
})

describe('routeHref', () => {
  it('round-trips every route', () => {
    const routes: Route[] = [
      { page: 'analyze' },
      { page: 'datasets' },
      { page: 'dataset', datasetId: 3, analysisId: null },
      { page: 'dataset', datasetId: 3, analysisId: 9 },
    ]
    for (const route of routes) {
      expect(parseRoute(routeHref(route))).toEqual(route)
    }
  })

  it('builds dataset links', () => {
    expect(datasetHref(4)).toBe('#/datasets/4')
    expect(datasetHref(4, 2)).toBe('#/datasets/4/analyses/2')
  })
})
