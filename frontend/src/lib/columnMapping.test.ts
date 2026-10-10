import { describe, expect, it } from 'vitest'
import {
  findConflicts,
  hasExplicitChoices,
  isSameMapping,
  mappingFormFields,
  resolveColumns,
  roleUsingColumn,
} from './columnMapping'

const SAMPLE_COLUMNS = ['order_id', 'order_date', 'store', 'quantity', 'unit_price']

describe('resolveColumns (mirrors the backend resolve_columns)', () => {
  it('uses columns named exactly like each role by default', () => {
    expect(resolveColumns(SAMPLE_COLUMNS, {})).toEqual({
      order_id: 'order_id',
      quantity: 'quantity',
      unit_price: 'unit_price',
      revenue: null,
    })
  })

  it('lets an explicit choice win over the exact-name match', () => {
    const resolved = resolveColumns(['Qty', 'quantity'], { quantity: 'Qty' })
    expect(resolved.quantity).toBe('Qty')
  })

  it('does not guess similar names: matching is exact and case-sensitive', () => {
    const resolved = resolveColumns(['Quantity', 'Unit Price', 'OrderID'], {})
    expect(resolved).toEqual({ order_id: null, quantity: null, unit_price: null, revenue: null })
  })

  it('treats an empty choice as automatic', () => {
    expect(resolveColumns(['quantity'], { quantity: '' }).quantity).toBe('quantity')
  })
})

describe('findConflicts', () => {
  it('reports a column chosen for two roles', () => {
    const resolved = resolveColumns(['amount'], { quantity: 'amount', revenue: 'amount' })
    expect(findConflicts(resolved)).toEqual(['amount'])
  })

  it('reports an explicit choice that collides with another role’s automatic match', () => {
    const resolved = resolveColumns(['revenue', 'qty'], { quantity: 'revenue' })
    expect(findConflicts(resolved)).toEqual(['revenue'])
  })

  it('finds nothing when every role has its own column', () => {
    expect(findConflicts(resolveColumns(SAMPLE_COLUMNS, {}))).toEqual([])
  })
})

describe('roleUsingColumn', () => {
  it('names the other role that already uses a column', () => {
    const resolved = resolveColumns(SAMPLE_COLUMNS, {})
    expect(roleUsingColumn(resolved, 'quantity', 'unit_price')).toBe('quantity')
    expect(roleUsingColumn(resolved, 'quantity', 'quantity')).toBeNull()
    expect(roleUsingColumn(resolved, 'store', 'revenue')).toBeNull()
  })
})

describe('mappingFormFields', () => {
  it('sends only explicit choices, using the backend form field names', () => {
    expect(mappingFormFields({ order_id: 'OrderNo', quantity: 'Qty', revenue: '' })).toEqual({
      order_id_column: 'OrderNo',
      quantity_column: 'Qty',
    })
  })

  it('sends nothing for a fully automatic mapping', () => {
    expect(mappingFormFields({})).toEqual({})
  })
})

describe('mapping comparisons', () => {
  it('treats missing and empty choices as the same', () => {
    expect(isSameMapping({ quantity: '' }, {})).toBe(true)
    expect(isSameMapping({ quantity: 'Qty' }, {})).toBe(false)
  })

  it('detects explicit choices', () => {
    expect(hasExplicitChoices({})).toBe(false)
    expect(hasExplicitChoices({ revenue: '' })).toBe(false)
    expect(hasExplicitChoices({ revenue: 'Sales' })).toBe(true)
  })
})
