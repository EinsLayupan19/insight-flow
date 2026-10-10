import { describe, expect, it } from 'vitest'
import { selectCsvFile } from './files'

const csv = (name: string, content = 'store,revenue\nNorth,100\n') => new File([content], name, { type: 'text/csv' })

describe('selectCsvFile', () => {
  it('accepts one .csv file, in any letter case', () => {
    for (const name of ['sales.csv', 'SALES.CSV']) {
      const result = selectCsvFile([csv(name)])
      expect(result.error).toBeNull()
      expect(result.file?.name).toBe(name)
    }
  })

  it('rejects files that are not .csv, like the backend does', () => {
    const result = selectCsvFile([csv('sales.xlsx')])
    expect(result.file).toBeNull()
    expect(result.error).toContain('is not a CSV file')
  })

  it('rejects an empty file', () => {
    const result = selectCsvFile([csv('empty.csv', '')])
    expect(result.file).toBeNull()
    expect(result.error).toContain('is empty')
  })

  it('rejects several files at once', () => {
    const result = selectCsvFile([csv('a.csv'), csv('b.csv')])
    expect(result.file).toBeNull()
    expect(result.error).toContain('one CSV file at a time')
  })

  it('only warns about large files, because the server decides the limit', () => {
    const big = new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'big.csv')
    const result = selectCsvFile([big])
    expect(result.file).toBe(big)
    expect(result.error).toBeNull()
    expect(result.warning).toContain('may be rejected')
  })

  it('returns an empty selection when nothing was chosen', () => {
    expect(selectCsvFile([])).toEqual({ file: null, error: null, warning: null })
  })
})
