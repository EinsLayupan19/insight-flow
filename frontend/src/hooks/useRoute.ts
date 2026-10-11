import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react'
import { parseRoute, type Route } from '../lib/route'

function subscribe(onChange: () => void) {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

const currentHash = () => window.location.hash

/** The page the URL hash points to. Updates on links, the back button, and navigate(). */
export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, currentHash)
  return useMemo(() => parseRoute(hash), [hash])
}

export function navigate(href: string): void {
  window.location.hash = href
}

/**
 * When a different page opens, start at the top and move keyboard focus to the main area,
 * so screen readers announce the new content. Switching analyses within a dataset does not count.
 */
export function usePageChangeFocus(route: Route, mainId: string): void {
  const pageKey = route.page === 'dataset' ? `dataset-${route.datasetId}` : route.page
  const isFirstRender = useRef(true)
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false
      return
    }
    window.scrollTo(0, 0)
    document.getElementById(mainId)?.focus()
  }, [pageKey, mainId])
}
