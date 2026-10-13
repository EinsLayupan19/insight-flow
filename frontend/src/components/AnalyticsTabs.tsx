// Tabs for the Analytics page (WAI-ARIA tabs, automatic activation). Every panel stays mounted and
// hidden panels use the `hidden` attribute, so choices made in one tab (a chart series, a table
// filter, an open form) are still there on return. Switching is instant: tabs are used too often to animate.

import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import { ANALYTICS_TABS, tabKeyTarget, type AnalyticsTab } from '../lib/tabs'

type AnalyticsTabsProps = {
  selected: AnalyticsTab
  onSelect: (tab: AnalyticsTab) => void
  panels: Record<AnalyticsTab, ReactNode>
}

export function AnalyticsTabs({ selected, onSelect, panels }: AnalyticsTabsProps) {
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])
  const selectedIndex = ANALYTICS_TABS.findIndex((tab) => tab.key === selected)

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const target = tabKeyTarget(event.key, selectedIndex, ANALYTICS_TABS.length)
    if (target === null) return
    event.preventDefault()
    onSelect(ANALYTICS_TABS[target].key)
    tabRefs.current[target]?.focus()
  }

  return (
    <>
      <div className="tab-list" role="tablist" aria-label="Analytics sections" onKeyDown={onKeyDown}>
        {ANALYTICS_TABS.map((tab, index) => {
          const isSelected = tab.key === selected
          return (
            <button
              key={tab.key}
              ref={(element) => {
                tabRefs.current[index] = element
              }}
              type="button"
              role="tab"
              id={`tab-${tab.key}`}
              className="tab"
              aria-selected={isSelected}
              aria-controls={`panel-${tab.key}`}
              tabIndex={isSelected ? 0 : -1}
              onClick={() => onSelect(tab.key)}
            >
              {tab.label}
            </button>
          )
        })}
      </div>

      {ANALYTICS_TABS.map((tab) => (
        <div
          key={tab.key}
          role="tabpanel"
          id={`panel-${tab.key}`}
          className="tab-panel"
          aria-labelledby={`tab-${tab.key}`}
          hidden={tab.key !== selected}
          tabIndex={0}
        >
          {panels[tab.key]}
        </div>
      ))}
    </>
  )
}
