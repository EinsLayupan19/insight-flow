import { navSection, routeHref, type NavSection, type Route } from '../lib/route'

const ITEMS: { section: NavSection; label: string; href: string }[] = [
  { section: 'overview', label: 'Overview', href: routeHref({ page: 'overview' }) },
  { section: 'datasets', label: 'Datasets', href: routeHref({ page: 'datasets' }) },
  { section: 'analytics', label: 'Analytics', href: routeHref({ page: 'analytics' }) },
]

export function AppNav({ route }: { route: Route }) {
  const current = navSection(route)
  return (
    <nav className="app-nav" aria-label="Main">
      {ITEMS.map((item) => (
        <a key={item.section} href={item.href} aria-current={item.section === current ? 'page' : undefined}>
          {item.label}
        </a>
      ))}
    </nav>
  )
}
