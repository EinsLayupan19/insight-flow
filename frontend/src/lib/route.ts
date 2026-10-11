// Pages and their URLs. Routes live in the URL hash (#/datasets/12), so links,
// reloads, and the browser's back button work without server configuration.

export type Route =
  | { page: 'analyze' }
  | { page: 'datasets' }
  | { page: 'dataset'; datasetId: number; analysisId: number | null }

const DATASET_PATH = /^\/datasets(?:\/([1-9][0-9]*)(?:\/analyses\/([1-9][0-9]*))?)?\/?$/

/** Anything that is not a dataset route (including an empty hash) shows the Analyze page. */
export function parseRoute(hash: string): Route {
  const match = DATASET_PATH.exec(hash.replace(/^#/, ''))
  if (!match) return { page: 'analyze' }
  if (!match[1]) return { page: 'datasets' }
  return { page: 'dataset', datasetId: Number(match[1]), analysisId: match[2] ? Number(match[2]) : null }
}

export function routeHref(route: Route): string {
  switch (route.page) {
    case 'analyze':
      return '#/'
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
