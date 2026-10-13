// Renders retail metrics from the API (calculated live, or recorded in a dataset's history).
// Only metrics the API returned are shown, with its own definitions, notes, and row counts.

import type { RetailMetrics } from '../api/uploads'
import { latestData, type RequestState } from '../lib/requestState'
import type { ColumnMapping } from '../lib/columnMapping'
import { METRIC_ORDER, describeMetric, hasUnavailableMetrics, revenueBasis } from '../lib/metricDisplay'
import { ColumnMappingPanel } from './ColumnMappingPanel'
import { Callout, LoadingState } from './Feedback'
import { Spinner } from './Icons'
import { MetricCard } from './MetricCard'

type MetricsSectionProps = {
  state: RequestState<RetailMetrics>
  columns: string[]
  appliedMapping: ColumnMapping
  onApplyMapping: (mapping: ColumnMapping) => void
  onRetry: () => void
}

export function MetricsSection({ state, columns, appliedMapping, onApplyMapping, onRetry }: MetricsSectionProps) {
  const data = latestData(state)
  const busy = state.status === 'loading'

  return (
    <section id="retail-metrics" className="card section-card" aria-labelledby="metrics-heading" aria-busy={busy}>
      <header className="section-header">
        <h2 id="metrics-heading">Key numbers</h2>
        <p>Calculated only from columns the file actually has. Each number shows the rows it used and how it is calculated.</p>
      </header>

      {state.status === 'error' && (
        <Callout
          tone="critical"
          title={data ? 'The key numbers could not be updated' : 'The key numbers could not be calculated'}
          action={
            <button type="button" className="button-secondary" onClick={onRetry}>
              Try again
            </button>
          }
        >
          {state.message}
          {data && ' The numbers below are from the last successful calculation.'}
        </Callout>
      )}

      {data !== null ? (
        <>
          <ColumnMappingPanel
            columns={columns}
            applied={appliedMapping}
            used={data.columns_used}
            busy={busy}
            showHint={hasUnavailableMetrics(data)}
            onApply={onApplyMapping}
          />
          {busy && (
            <p className="updating-note" role="status">
              <Spinner /> Recalculating key numbers…
            </p>
          )}
          {/* While recalculating, the previous results stay visible but dimmed. */}
          <div className={busy ? 'metrics-body is-stale' : 'metrics-body'}>
            <MetricsView metrics={data} />
          </div>
        </>
      ) : (
        state.status !== 'error' && <LoadingState>Calculating key numbers…</LoadingState>
      )}
    </section>
  )
}

export function MetricsView({ metrics }: { metrics: RetailMetrics }) {
  const basis = revenueBasis(metrics)
  return (
    <>
      <div className="metric-grid">
        {METRIC_ORDER.map((key) => (
          <MetricCard key={key} id={`metric-${key}`} metric={metrics[key]} presentation={describeMetric(key, basis)} />
        ))}
      </div>

      <details className="disclosure">
        <summary>How numbers are read</summary>
        <p>{metrics.number_rule}</p>
      </details>

      <ul className="footnotes">
        <li>Amounts have no currency symbol because the file does not say which currency it uses.</li>
        <li>
          Not calculated: profit, margin, and net revenue. They need cost data and agreed definitions for returns and
          refunds.
        </li>
      </ul>
    </>
  )
}
