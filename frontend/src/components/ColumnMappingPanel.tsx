// Optional column mapping for the metrics endpoint. Collapsed by default; it shows which
// column each role uses and lets the user pick different ones. The backend validates
// every mapping again and answers HTTP 422 if it is not allowed.

import { useState } from 'react'
import {
  METRIC_ROLES,
  ROLE_LABELS,
  findConflicts,
  hasExplicitChoices,
  isSameMapping,
  resolveColumns,
  roleUsingColumn,
  type ColumnMapping,
  type MetricRole,
} from '../lib/columnMapping'
import { Callout } from './Feedback'

type ColumnMappingPanelProps = {
  columns: string[]
  /** Explicit choices behind the metrics currently shown. */
  applied: ColumnMapping
  /** The column the API actually used for each role. */
  used: Record<MetricRole, string | null>
  busy: boolean
  showHint: boolean
  onApply: (mapping: ColumnMapping) => void
}

export function ColumnMappingPanel({ columns, applied, used, busy, showHint, onApply }: ColumnMappingPanelProps) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<ColumnMapping>(applied)
  const [draftSource, setDraftSource] = useState<ColumnMapping>(applied)
  if (!isSameMapping(draftSource, applied)) {
    // A different mapping was applied: continue editing from it.
    setDraftSource(applied)
    setDraft(applied)
  }

  const resolved = resolveColumns(columns, draft)
  const conflicts = findConflicts(resolved)
  const canApply = !busy && !isSameMapping(draft, applied) && conflicts.length === 0

  const choose = (role: MetricRole, column: string) =>
    setDraft((current) => {
      const next = { ...current }
      if (column) next[role] = column
      else delete next[role]
      return next
    })

  return (
    <div className="mapping">
      <div className="mapping-summary">
        <div>
          <h4 className="mapping-heading">Columns used</h4>
          <dl className="columns-used">
            {METRIC_ROLES.map((role) => (
              <div key={role}>
                <dt>{ROLE_LABELS[role]}</dt>
                <dd>{used[role] ? <code>{used[role]}</code> : <span className="muted">Not found</span>}</dd>
              </div>
            ))}
          </dl>
        </div>
        <button
          type="button"
          className="button-secondary"
          aria-expanded={open}
          aria-controls="column-mapping-form"
          onClick={() => setOpen((isOpen) => !isOpen)}
        >
          {open ? 'Hide column mapping' : 'Map columns'}
        </button>
      </div>

      {showHint && !open && (
        <p className="mapping-hint">
          Some metrics are unavailable. If your file uses different column names, choose them with <strong>Map columns</strong>.
        </p>
      )}

      {open && (
        <form
          id="column-mapping-form"
          className="mapping-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (canApply) onApply(draft)
          }}
        >
          <p className="small muted">
            By default, each role uses the column with exactly that name (letter case included). Choose a column to use
            a different one. Nothing is guessed, and each column can fill only one role.
          </p>
          <div className="mapping-grid">
            {METRIC_ROLES.map((role) => (
              <div className="field" key={role}>
                <label htmlFor={`map-${role}`}>{ROLE_LABELS[role]}</label>
                <select
                  id={`map-${role}`}
                  value={draft[role] ?? ''}
                  disabled={busy}
                  onChange={(event) => choose(role, event.target.value)}
                >
                  <option value="">{columns.includes(role) ? `Automatic (${role})` : `Automatic (no "${role}" column)`}</option>
                  {columns.map((column) => {
                    const otherRole = roleUsingColumn(resolved, column, role)
                    return (
                      <option key={column} value={column} disabled={otherRole !== null}>
                        {otherRole ? `${column} (used for ${ROLE_LABELS[otherRole]})` : column}
                      </option>
                    )
                  })}
                </select>
              </div>
            ))}
          </div>

          {conflicts.length > 0 && (
            <Callout tone="critical">
              Each column can fill only one role. Used more than once: {conflicts.join(', ')}.
            </Callout>
          )}

          <div className="form-actions">
            <button type="submit" className="button-primary" disabled={!canApply}>
              Apply mapping
            </button>
            <button type="button" className="button-ghost" disabled={busy || !hasExplicitChoices(draft)} onClick={() => setDraft({})}>
              Reset to automatic
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
