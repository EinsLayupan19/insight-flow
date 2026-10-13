// Tabs on the Analytics page. Keyboard behavior follows the WAI-ARIA tabs pattern with automatic
// activation: the arrow keys move between tabs (wrapping at the ends), Home and End jump to the
// first and last, and Tab leaves the tab list for the open panel.

export type AnalyticsTab = 'summary' | 'trends' | 'products' | 'quality'

export const ANALYTICS_TABS: readonly { key: AnalyticsTab; label: string }[] = [
  { key: 'summary', label: 'Summary' },
  { key: 'trends', label: 'Trends' },
  { key: 'products', label: 'Products' },
  { key: 'quality', label: 'Data quality' },
]

/** The tab a key press moves to, or null when the key is not a tab-list key. */
export function tabKeyTarget(key: string, current: number, count: number): number | null {
  if (count === 0) return null
  switch (key) {
    case 'ArrowRight':
      return (current + 1) % count
    case 'ArrowLeft':
      return (current - 1 + count) % count
    case 'Home':
      return 0
    case 'End':
      return count - 1
    default:
      return null
  }
}
