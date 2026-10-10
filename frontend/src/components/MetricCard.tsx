// One metric from POST /api/uploads/csv/metrics, with the evidence the API returned:
// definition, columns used, rows included/excluded, and notes. Nothing is recalculated here.

import type { MetricResult } from '../api/uploads'
import { formatCount, formatMetricValue, pluralize } from '../lib/format'
import type { MetricPresentation } from '../lib/metricDisplay'
import { StatusBadge } from './Feedback'
import { AlertIcon, InfoIcon } from './Icons'

type MetricCardProps = {
  id: string
  metric: MetricResult
  presentation: MetricPresentation
}

export function MetricCard({ id, metric, presentation }: MetricCardProps) {
  const value = metric.status === 'calculated' ? metric.value : null
  const formatted = value === null ? null : formatMetricValue(value, presentation.format)
  const labelId = `${id}-label`

  return (
    <article id={id} className={formatted ? 'metric-card' : 'metric-card is-unavailable'} aria-labelledby={labelId}>
      <div className="metric-card-header">
        <h4 id={labelId} className="metric-label">
          {presentation.label}
        </h4>
        {formatted ? (
          <StatusBadge tone="good">Calculated</StatusBadge>
        ) : (
          <StatusBadge tone="neutral">Unavailable</StatusBadge>
        )}
      </div>

      {formatted ? (
        <>
          <p className="metric-value">{formatted.text}</p>
          {formatted.isRounded && (
            <p className="metric-exact">
              Rounded for display. Exact value: <span className="num">{formatted.exact}</span>
            </p>
          )}
          {presentation.caption && <p className="metric-caption">{presentation.caption}</p>}
          <RowsUsed metric={metric} />
        </>
      ) : (
        <p className="metric-value metric-value-missing">Not available</p>
      )}

      {metric.notes.length > 0 && (
        <ul className={formatted ? 'metric-notes notes-warning' : 'metric-notes notes-info'}>
          {metric.notes.map((note) => (
            <li key={note}>
              {formatted ? (
                <AlertIcon size={15} className="tone-icon tone-warning" />
              ) : (
                <InfoIcon size={15} className="tone-icon tone-info" />
              )}
              <span>{note}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="metric-footer">
        {metric.columns_used.length > 0 && (
          <p className="metric-columns">
            <span className="muted">Columns used:</span>{' '}
            {metric.columns_used.map((column) => (
              <code key={column}>{column}</code>
            ))}
          </p>
        )}
        <p className="metric-definition">
          <span className="muted">Definition:</span> {metric.definition}
        </p>
      </div>
    </article>
  )
}

function RowsUsed({ metric }: { metric: MetricResult }) {
  if (metric.rows_included === null || metric.rows_excluded === null) return null
  const total = metric.rows_included + metric.rows_excluded
  return (
    <p className="metric-rows">
      Based on {formatCount(metric.rows_included)} of {pluralize(total, 'row')}
      {metric.rows_excluded > 0 ? ` · ${formatCount(metric.rows_excluded)} excluded` : ''}
    </p>
  )
}
