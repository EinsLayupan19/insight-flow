import { describe, expect, it } from 'vitest'
import { ANALYTICS_TABS, tabKeyTarget } from './tabs'

describe('tabKeyTarget', () => {
  it('moves to the next and previous tab with the arrow keys', () => {
    expect(tabKeyTarget('ArrowRight', 0, 4)).toBe(1)
    expect(tabKeyTarget('ArrowLeft', 2, 4)).toBe(1)
  })

  it('wraps around at either end', () => {
    expect(tabKeyTarget('ArrowRight', 3, 4)).toBe(0)
    expect(tabKeyTarget('ArrowLeft', 0, 4)).toBe(3)
  })

  it('jumps to the first and last tab with Home and End', () => {
    expect(tabKeyTarget('Home', 2, 4)).toBe(0)
    expect(tabKeyTarget('End', 1, 4)).toBe(3)
  })

  it('ignores every other key, so Tab and Enter keep their usual meaning', () => {
    for (const key of ['Tab', 'Enter', ' ', 'ArrowUp', 'ArrowDown', 'a']) {
      expect(tabKeyTarget(key, 1, 4)).toBeNull()
    }
  })

  it('does nothing when there are no tabs', () => {
    expect(tabKeyTarget('ArrowRight', 0, 0)).toBeNull()
    expect(tabKeyTarget('End', 0, 0)).toBeNull()
  })
})

describe('ANALYTICS_TABS', () => {
  it('lists Summary, Trends, Products, and Data quality in that order', () => {
    expect(ANALYTICS_TABS.map((tab) => tab.label)).toEqual(['Summary', 'Trends', 'Products', 'Data quality'])
  })

  it('gives every tab a unique key', () => {
    const keys = ANALYTICS_TABS.map((tab) => tab.key)
    expect(new Set(keys).size).toBe(keys.length)
  })
})
