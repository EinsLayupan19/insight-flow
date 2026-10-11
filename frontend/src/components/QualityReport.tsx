// Renders a data-quality report from the API (profiled live, or recorded in a dataset's history).
// Every number shown comes from the API; the summary tiles only add up its per-column counts.

import { useState } from 'react'
import type { ColumnProfile, QualityReport } from '../api/uploads'
import { latestData, type RequestState } from '../lib/requestState'
import { formatCount, formatPercent, pluralize } from '../lib/format'
import { Callout, LoadingState, StatusBadge } from './Feedback'

type QualitySectionProps = {
  state: RequestState<QualityReport>
  onRetry: () => void
}

export function QualitySection({ state, onRetry }: QualitySectionProps) {
  const data = latestData(state)

  return (
    <section id="data-quality" className="card section-card" aria-labelledby="quality-heading" aria-busy={state.status === 'loading'}>
      <header className="section-header">
        <h3 id="quality-heading">Data quality</h3>
        <p>What the checks found in the file as uploaded. Findings are reported, never fixed or removed.</p>
      </header>

      {state.status === 'error' && (
        <Callout
          tone="critical"
          title="The data-quality profile could not be created"
          action={
            <button type="button" className="button-secondary" onClick={onRetry}>
              Try again
            </button>
          }
        >
          {state.message}
        </Callout>
      )}

      {data !== null ? (
        <QualityReportView report={data} />
      ) : (
        state.status !== 'error' && <LoadingState>Profiling data quality…</LoadingState>
      )}
    </section>
  )
}

function hasFindings(column: ColumnProfile): boolean {
  return column.missing_count > 0 || column.mismatch_count > 0
}

function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0)
}

export function QualityReportView({ report }: { report: QualityReport }) {
  const withMissing = report.columns.filter((column) => column.missing_count > 0)
  const withMismatches = report.columns.filter((column) => column.mismatch_count > 0)
  const anyFindings = report.duplicate_row_count > 0 || withMissing.length > 0 || withMismatches.length > 0

  return (
    <>
      <dl className="tile-row">
        <StatTile label="Rows" value={formatCount(report.row_count)} />
        <StatTile label="Columns" value={formatCount(report.column_count)} />
        <StatTile
          label="Duplicate rows"
          value={formatCount(report.duplicate_row_count)}
          detail={`${formatPercent(report.duplicate_row_percent)} of rows`}
        />
        <StatTile
          label="Missing values"
          value={formatCount(sum(withMissing.map((column) => column.missing_count)))}
          detail={`in ${pluralize(withMissing.length, 'column')}`}
        />
        <StatTile
          label="Type mismatches"
          value={formatCount(sum(withMismatches.map((column) => column.mismatch_count)))}
          detail={`in ${pluralize(withMismatches.length, 'column')}`}
        />
      </dl>

      {anyFindings ? (
        <Callout tone="warning" title="Review these findings before relying on the metrics">
          The metrics use the data exactly as uploaded, duplicate rows included. Blank values and values that are not
          usable numbers are left out of each metric and counted, never treated as zero.
        </Callout>
      ) : (
        <Callout tone="good" title="No issues found by these checks">
          No missing values, duplicate rows, or type mismatches. The checks are defined at the end of this section.
        </Callout>
      )}

      {report.duplicate_row_count > 0 && <DuplicateRows report={report} />}
      <ColumnTable columns={report.columns} />
      <Definitions definitions={report.definitions} />
    </>
  )
}

function StatTile({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="stat-tile">
      <dt className="stat-label">{label}</dt>
      <dd className="stat-value">{value}</dd>
      {detail && <dd className="stat-detail">{detail}</dd>}
    </div>
  )
}

function DuplicateRows({ report }: { report: QualityReport }) {
  const shown = report.duplicate_examples.length
  return (
    <div className="subsection">
      <h4>Duplicate rows</h4>
      <ul className="evidence-list">
        {report.duplicate_examples.map((example) => (
          <li key={example.line}>
            Line {example.line} is an exact copy of line {example.duplicate_of_line}.
          </li>
        ))}
      </ul>
      {report.duplicate_row_count > shown && (
        <p className="small muted">
          Showing the first {shown} of {formatCount(report.duplicate_row_count)} duplicate rows.
        </p>
      )}
    </div>
  )
}

function ColumnTable({ columns }: { columns: ColumnProfile[] }) {
  const [onlyFindings, setOnlyFindings] = useState(false)
  const withFindings = columns.filter(hasFindings)
  const visible = onlyFindings ? withFindings : columns

  return (
    <div className="subsection">
      <div className="table-toolbar">
        <h4 id="columns-heading">Columns</h4>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={onlyFindings}
            disabled={withFindings.length === 0}
            onChange={(event) => setOnlyFindings(event.target.checked)}
          />
          Only columns with findings ({withFindings.length})
        </label>
      </div>

      {visible.length === 0 ? (
        <p className="empty-state">No columns to show.</p>
      ) : (
        <>
          <p className="table-hint small muted">Scroll the table sideways to see every column.</p>
          {/* The region is focusable so keyboard users can scroll a wide table sideways. */}
          <div className="table-scroll" role="region" aria-labelledby="columns-heading" tabIndex={0}>
            <table className="data-table">
              <caption className="sr-only">
                Data-quality findings per column, showing {visible.length} of {columns.length} columns
              </caption>
              <thead>
                <tr>
                  <th scope="col">Column</th>
                  <th scope="col">Inferred type</th>
                  <th scope="col">Missing values</th>
                  <th scope="col">Type mismatches</th>
                  <th scope="col">Values by type</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((column) => (
                  <ColumnRow key={column.name} column={column} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {onlyFindings && (
        <p className="small muted">
          Showing {visible.length} of {pluralize(columns.length, 'column')}.
        </p>
      )}
    </div>
  )
}

function ColumnRow({ column }: { column: ColumnProfile }) {
  const flagged = hasFindings(column)
  return (
    <tr>
      <th scope="row">
        <code className="column-name">{column.name}</code>
      </th>
      <td>
        <span className="type-chip">{column.inferred_type}</span>
      </td>
      <td>
        <MissingCell column={column} />
      </td>
      <td>
        <MismatchCell column={column} />
      </td>
      <td>
        <TypeCounts counts={column.type_counts} />
      </td>
      <td>
        <StatusBadge tone={flagged ? 'warning' : 'good'}>{flagged ? 'Review' : 'No findings'}</StatusBadge>
      </td>
    </tr>
  )
}

function MissingCell({ column }: { column: ColumnProfile }) {
  const percent = Math.min(100, column.missing_percent)
  return (
    <div className="meter-cell">
      {/* The bar is a visual aid only; the count and percentage are the data. */}
      <span className="meter" aria-hidden="true">
        {percent > 0 && <span className="meter-fill" style={{ width: `max(2px, ${percent}%)` }} />}
      </span>
      <span className={column.missing_count === 0 ? 'num muted' : 'num'}>
        {formatCount(column.missing_count)} <span className="muted">({formatPercent(column.missing_percent)})</span>
      </span>
    </div>
  )
}

function MismatchCell({ column }: { column: ColumnProfile }) {
  if (column.mismatch_count === 0) return <span className="num muted">0</span>

  const notShown = column.mismatch_count - column.mismatch_examples.length
  return (
    <div className="mismatch-cell">
      <span className="num">{formatCount(column.mismatch_count)}</span>
      <ul className="example-list" aria-label={`Mismatched values in ${column.name}`}>
        {column.mismatch_examples.map((example) => (
          <li key={example.line}>
            Line {example.line}: <code className="cell-value">{example.value}</code>
          </li>
        ))}
      </ul>
      {notShown > 0 && <span className="small muted">and {formatCount(notShown)} more</span>}
    </div>
  )
}

function TypeCounts({ counts }: { counts: ColumnProfile['type_counts'] }) {
  const entries = Object.entries(counts)
  if (entries.length === 0) return <span className="muted">No values</span>
  return (
    <ul className="type-counts">
      {entries.map(([type, count]) => (
        <li key={type}>
          {type} <span className="num">{formatCount(count ?? 0)}</span>
        </li>
      ))}
    </ul>
  )
}

function Definitions({ definitions }: { definitions: Record<string, string> }) {
  return (
    <details className="disclosure">
      <summary>How these checks are defined</summary>
      <dl className="definition-list">
        {Object.entries(definitions).map(([name, text]) => (
          <div key={name}>
            <dt>
              <code>{name}</code>
            </dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}
