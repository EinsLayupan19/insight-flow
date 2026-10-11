import { routeHref, type Route } from '../lib/route'

export function AppNav({ route }: { route: Route }) {
  const inLibrary = route.page !== 'analyze'
  return (
    <nav className="app-nav" aria-label="Main">
      <a href={routeHref({ page: 'analyze' })} aria-current={inLibrary ? undefined : 'page'}>
        Analyze a file
      </a>
      <a href={routeHref({ page: 'datasets' })} aria-current={inLibrary ? 'page' : undefined}>
        Saved datasets
      </a>
    </nav>
  )
}
