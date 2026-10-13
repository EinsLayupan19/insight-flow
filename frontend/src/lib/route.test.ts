import { describe, expect, it } from 'vitest'
import { datasetHref, navSection, parseRoute, routeHref, type Route } from './route'

describe('parseRoute', () => {
  it('opens the Overview page for an empty or unknown hash', () => {
    for (const hash of ['', '#', '#/', '#data-quality', '#/settings', '#/datasets/abc', '#/analytics/extra']) {
      expect(parseRoute(hash)).toEqual({ page: 'overview' })
    }
  })

  it('reads the Analytics page', () => {
    expect(parseRoute('#/analytics')).toEqual({ page: 'analytics' })
    expect(parseRoute('#/analytics/')).toEqual({ page: 'analytics' })
  })

  it('reads the dataset list, a dataset, and one of its analyses', () => {
    expect(parseRoute('#/datasets')).toEqual({ page: 'datasets' })
    expect(parseRoute('#/datasets/')).toEqual({ page: 'datasets' })
    expect(parseRoute('#/datasets/12')).toEqual({ page: 'dataset', datasetId: 12, analysisId: null })
    expect(parseRoute('#/datasets/12/analyses/5')).toEqual({ page: 'dataset', datasetId: 12, analysisId: 5 })
  })

  it('rejects ids that cannot exist', () => {
    expect(parseRoute('#/datasets/0')).toEqual({ page: 'overview' })
    expect(parseRoute('#/datasets/12/analyses/-1')).toEqual({ page: 'overview' })
  })
})

describe('routeHref', () => {
  it('keeps the Overview at the root and Analytics at #/analytics', () => {
    expect(routeHref({ page: 'overview' })).toBe('#/')
    expect(routeHref({ page: 'analytics' })).toBe('#/analytics')
  })

  it('round-trips every route', () => {
    const routes: Route[] = [
      { page: 'overview' },
      { page: 'analytics' },
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

describe('navSection', () => {
  it('marks the main navigation item each page belongs to', () => {
    expect(navSection({ page: 'overview' })).toBe('overview')
    expect(navSection({ page: 'analytics' })).toBe('analytics')
    expect(navSection({ page: 'datasets' })).toBe('datasets')
  })

  it('keeps a single dataset under Datasets', () => {
    expect(navSection({ page: 'dataset', datasetId: 3, analysisId: null })).toBe('datasets')
    expect(navSection({ page: 'dataset', datasetId: 3, analysisId: 9 })).toBe('datasets')
  })
})
