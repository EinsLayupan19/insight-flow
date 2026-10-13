// Pages and their URLs. Routes live in the URL hash (#/datasets/12), so links,
// reloads, and the browser's back button work without server configuration.

export type Route =
  | { page: 'overview' }
  | { page: 'analytics' }
  | { page: 'datasets' }
  | { page: 'dataset'; datasetId: number; analysisId: number | null }

/** The three items of the main navigation. */
export type NavSection = 'overview' | 'datasets' | 'analytics'

const ANALYTICS_PATH = /^\/analytics\/?$/
const DATASET_PATH = /^\/datasets(?:\/([1-9][0-9]*)(?:\/analyses\/([1-9][0-9]*))?)?\/?$/

/** Anything that is not a known route (including an empty hash) shows the Overview. */
export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#/, '')
  if (ANALYTICS_PATH.test(path)) return { page: 'analytics' }
  const match = DATASET_PATH.exec(path)
  if (!match) return { page: 'overview' }
  if (!match[1]) return { page: 'datasets' }
  return { page: 'dataset', datasetId: Number(match[1]), analysisId: match[2] ? Number(match[2]) : null }
}

export function routeHref(route: Route): string {
  switch (route.page) {
    case 'overview':
      return '#/'
    case 'analytics':
      return '#/analytics'
    case 'datasets':
      return '#/datasets'
    case 'dataset':
      return route.analysisId === null
        ? `#/datasets/${route.datasetId}`
        : `#/datasets/${route.datasetId}/analyses/${route.analysisId}`
  }
}

export const datasetHref = (datasetId: number, analysisId: number | null = null) =>
  routeHref({ page: 'dataset', datasetId, analysisId })

/** The navigation item a page sits under: a single dataset belongs to Datasets. */
export function navSection(route: Route): NavSection {
  return route.page === 'dataset' ? 'datasets' : route.page
}
