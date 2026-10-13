// The evidence the API returns with every measure: notes, rows used, columns used, and the
// definition. Shared by the trends and the product and category performance sections.

import { formatCount, pluralize } from '../lib/format'
import { AlertIcon, InfoIcon } from './Icons'

/** Notes from the API. Warnings for a calculated value; information for an unavailable one. */
export function Notes({ notes, tone }: { notes: string[]; tone: 'warning' | 'info' }) {
  if (notes.length === 0) return null
  return (
    <ul className={tone === 'warning' ? 'metric-notes notes-warning' : 'metric-notes notes-info'}>
      {notes.map((note) => (
        <li key={note}>
          {tone === 'warning' ? <AlertIcon size={15} className="tone-icon tone-warning" /> : <InfoIcon size={15} className="tone-icon tone-info" />}
          <span>{note}</span>
        </li>
      ))}
    </ul>
  )
}

type Measured = {
  notes: string[]
  rows_included: number | null
  rows_excluded: number | null
  columns_used: string[]
  definition: string
}

/** A calculated measure's notes, the rows and columns it used, and its definition. */
export function MeasureEvidence({ measure }: { measure: Measured }) {
  return (
    <div className="measure-evidence">
      <Notes notes={measure.notes} tone="warning" />
      {measure.rows_included !== null && measure.rows_excluded !== null && (
        <p className="metric-rows">
          Based on {formatCount(measure.rows_included)} of {pluralize(measure.rows_included + measure.rows_excluded, 'row')}
          {measure.rows_excluded > 0 ? `, ${formatCount(measure.rows_excluded)} excluded` : ''}
        </p>
      )}
      <details className="metric-footer evidence-details">
        <summary>How it's calculated</summary>
        {measure.columns_used.length > 0 && (
          <p className="metric-columns">
            <span className="muted">Columns used:</span>{' '}
            {measure.columns_used.map((column) => (
              <code key={column}>{column}</code>
            ))}
          </p>
        )}
        <p className="metric-definition">
          <span className="muted">Definition:</span> {measure.definition}
        </p>
      </details>
    </div>
  )
}
