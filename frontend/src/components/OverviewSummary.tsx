// The Overview's short answer for the latest analysis: the key numbers, the data-quality status,
// and the top findings, each linking to its full report (with the evidence) on the Analytics page.

import type { SaveDatasetResponse } from '../api/datasets'
import type { Analysis } from '../hooks/useCsvAnalysis'
import { formatBytes, formatDateTime, formatMetricValue, pluralize } from '../lib/format'
import { describeMetric, revenueBasis, type MetricKey } from '../lib/metricDisplay'
import { qualitySummary, topFindings } from '../lib/overview'
import { latestData, type RequestState } from '../lib/requestState'
import { datasetHref, routeHref } from '../lib/route'
import type { AnalyticsTab } from '../lib/tabs'
import type { RetailMetrics } from '../api/uploads'
import { Callout, LoadingState, StatusBadge } from './Feedback'

const KEY_NUMBERS: readonly MetricKey[] = ['total_revenue', 'order_count', 'average_order_value']
const ANALYTICS_HREF = routeHref({ page: 'analytics' })

type OverviewSummaryProps = {
  analysis: Analysis
  onOpenAnalytics: (tab: AnalyticsTab) => void
  onRetryMetrics: () => void
  onRetryProfile: () => void
  onRetryInsights: () => void
  onClear: () => void
}

export function OverviewSummary({ analysis, onOpenAnalytics, onRetryMetrics, onRetryProfile, onRetryInsights, onClear }: OverviewSummaryProps) {
  if (analysis.validation.status !== 'success') return null
  const summary = analysis.validation.data
  /** A link to one Analytics tab: an ordinary link, so it can also open in a new tab. */
  const open = (tab: AnalyticsTab, label: string, className?: string) => (
    <a className={className} href={ANALYTICS_HREF} onClick={() => onOpenAnalytics(tab)}>
      {label}
    </a>
  )

  return (
    <section className="card overview-summary" aria-labelledby="overview-results-heading">
      <div className="card-header overview-summary-header">
        <div>
          <h2 id="overview-results-heading">{analysis.file.name}</h2>
          <p className="small muted">
            {pluralize(summary.row_count, 'row')}, {pluralize(summary.column_count, 'column')}, {formatBytes(summary.size_bytes)}
            {analysis.saved === null && '. Analyzed in memory, not stored'}
          </p>
        </div>
        <button type="button" className="button-ghost" onClick={onClear}>
          Clear results
        </button>
      </div>

      {analysis.saved && <SavedNotice saved={analysis.saved} />}

      <div className="overview-block">
        <h3>Key numbers</h3>
        <KeyNumbers state={analysis.metrics} onRetry={onRetryMetrics} />
        <p className="small muted">
          Profit and margin are not calculated: they need cost data, which InsightFlow does not read.
        </p>
      </div>

      <div className="overview-block">
        <h3>Data quality</h3>
        <QualityLine state={analysis.profile} onRetry={onRetryProfile} />
        {latestData(analysis.profile) && open('quality', 'Review data quality')}
      </div>

      <div className="overview-block">
        <h3>Top findings</h3>
        <TopFindings state={analysis.insights} onRetry={onRetryInsights} />
      </div>

      <div className="overview-next">
        {open('summary', 'Open analytics', 'button-primary')}
        <p className="small muted">Trends over time, product rankings, and the evidence behind every number.</p>
      </div>
    </section>
  )
}

function SavedNotice({ saved }: { saved: SaveDatasetResponse }) {
  const { dataset } = saved
  const link = (
    <a className="button-secondary" href={datasetHref(dataset.id)}>
      View dataset and history
    </a>
  )
  if (saved.created) {
    return (
      <Callout tone="good" title="Saved to your datasets" action={link}>
        The file is stored on the InsightFlow server as dataset #{dataset.id}. These results are recorded in its history.
      </Callout>
    )
  }
  return (
    <Callout tone="info" title="Already in your datasets" action={link}>
      The same content was saved on {formatDateTime(dataset.created_at)} as “{dataset.filename}” (dataset #{dataset.id}).
      No second copy was stored; these results were added to that dataset's history.
    </Callout>
  )
}

function RetryCallout({ title, message, onRetry }: { title: string; message: string; onRetry: () => void }) {
  return (
    <Callout
      tone="critical"
      title={title}
      action={
        <button type="button" className="button-secondary" onClick={onRetry}>
          Try again
        </button>
      }
    >
      {message}
    </Callout>
  )
}

function KeyNumbers({ state, onRetry }: { state: RequestState<RetailMetrics>; onRetry: () => void }) {
  const metrics = latestData(state)
  if (state.status === 'error' && metrics === null) {
    return <RetryCallout title="The key numbers could not be calculated" message={state.message} onRetry={onRetry} />
  }
  if (metrics === null) return <LoadingState>Calculating key numbers…</LoadingState>

  const basis = revenueBasis(metrics)
  return (
    <dl className={state.status === 'loading' ? 'tile-row key-numbers is-stale' : 'tile-row key-numbers'}>
      {KEY_NUMBERS.map((key) => {
        const metric = metrics[key]
        const presentation = describeMetric(key, basis)
        return (
          <div key={key} className="stat-tile">
            <dt className="stat-label">{presentation.label}</dt>
            {metric.status === 'calculated' && metric.value !== null ? (
              <dd className="stat-value">{formatMetricValue(metric.value, presentation.format).text}</dd>
            ) : (
              <dd className="stat-value stat-value-missing">Not available</dd>
            )}
            {presentation.caption && <dd className="stat-detail">{presentation.caption}</dd>}
          </div>
        )
      })}
    </dl>
  )
}

function QualityLine({ state, onRetry }: { state: Analysis['profile']; onRetry: () => void }) {
  const report = latestData(state)
  if (state.status === 'error' && report === null) {
    return <RetryCallout title="The data-quality check could not run" message={state.message} onRetry={onRetry} />
  }
  if (report === null) return <LoadingState>Checking data quality…</LoadingState>

  const { clean, text } = qualitySummary(report)
  return (
    <p className="quality-line">
      <StatusBadge tone={clean ? 'good' : 'warning'}>{clean ? 'No issues found' : 'Worth reviewing'}</StatusBadge>
      <span>{text}</span>
    </p>
  )
}

function TopFindings({ state, onRetry }: { state: Analysis['insights']; onRetry: () => void }) {
  const insights = latestData(state)
  if (state.status === 'error' && insights === null) {
    return <RetryCallout title="The findings could not be calculated" message={state.message} onRetry={onRetry} />
  }
  if (insights === null) return <LoadingState>Finding what stands out…</LoadingState>

  const top = topFindings(insights, 3)
  if (top.length === 0) {
    return <p className="muted">Nothing stands out in this file. The Summary tab lists the checks that ran.</p>
  }
  return (
    <ol className="overview-findings">
      {top.map((insight) => (
        <li key={insight.id}>
          <p className="overview-finding-title">{insight.title}</p>
          <p className="overview-finding-statement">{insight.statement}</p>
        </li>
      ))}
    </ol>
  )
}
