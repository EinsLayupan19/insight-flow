import { AnalyticsTabs } from '../components/AnalyticsTabs'
import { Callout, LoadingState } from '../components/Feedback'
import { KeyFindingsSection } from '../components/KeyFindings'
import { MetricsSection } from '../components/MetricsReport'
import { PerformanceSection } from '../components/PerformanceReport'
import { QualitySection } from '../components/QualityReport'
import { TrendsSection } from '../components/TrendsReport'
import type { CsvAnalysisController } from '../hooks/useCsvAnalysis'
import { formatBytes, pluralize } from '../lib/format'
import { datasetHref, routeHref } from '../lib/route'
import type { AnalyticsTab } from '../lib/tabs'

type AnalyticsPageProps = {
  csv: CsvAnalysisController
  tab: AnalyticsTab
  onTabChange: (tab: AnalyticsTab) => void
}

/** The full results of the latest analysis, in four tabs. The analysis itself lives in App. */
export function AnalyticsPage({ csv, tab, onTabChange }: AnalyticsPageProps) {
  const { analysis } = csv

  if (analysis === null) {
    return (
      <>
        <PageIntro />
        <div className="empty-panel">
          <p className="empty-title">Nothing analyzed yet</p>
          <p>Upload a CSV file on the Overview page, or open a saved dataset to see the analyses recorded for it.</p>
          <div className="empty-actions">
            <a className="button-primary" href={routeHref({ page: 'overview' })}>
              Upload a file
            </a>
            <a className="button-secondary" href={routeHref({ page: 'datasets' })}>
              Open datasets
            </a>
          </div>
        </div>
      </>
    )
  }

  if (analysis.validation.status === 'loading' || analysis.validation.status === 'idle') {
    return (
      <>
        <PageIntro />
        <section className="card">
          <LoadingState>Checking {analysis.file.name}…</LoadingState>
          <p className="small muted">
            Progress, and the option to cancel, are on the <a href={routeHref({ page: 'overview' })}>Overview</a>.
          </p>
        </section>
      </>
    )
  }

  if (analysis.validation.status === 'error') {
    return (
      <>
        <PageIntro />
        <Callout
          tone="critical"
          title={`${analysis.file.name} could not be analyzed`}
          action={
            <>
              <button type="button" className="button-secondary" onClick={csv.retryAnalysis}>
                Try again
              </button>
              <a className="button-ghost" href={routeHref({ page: 'overview' })}>
                Choose a different file
              </a>
            </>
          }
        >
          {analysis.validation.message}
        </Callout>
      </>
    )
  }

  const summary = analysis.validation.data
  return (
    <>
      <section className="intro analytics-intro">
        <div>
          <h1>Analytics</h1>
          <p>
            <strong className="file-label">{analysis.file.name}</strong>: {pluralize(summary.row_count, 'row')},{' '}
            {pluralize(summary.column_count, 'column')}, {formatBytes(summary.size_bytes)}.{' '}
            {analysis.saved ? (
              <>
                Saved as <a href={datasetHref(analysis.saved.dataset.id)}>dataset #{analysis.saved.dataset.id}</a>.
              </>
            ) : (
              'Analyzed in memory, not stored.'
            )}
          </p>
        </div>
        <button type="button" className="button-secondary" onClick={csv.clearResults}>
          Clear results
        </button>
      </section>

      <AnalyticsTabs
        selected={tab}
        onSelect={onTabChange}
        panels={{
          summary: (
            <div className="tab-stack">
              <KeyFindingsSection state={analysis.insights} onRetry={csv.retryInsights} />
              <MetricsSection
                state={analysis.metrics}
                columns={summary.columns}
                appliedMapping={analysis.appliedMapping}
                onApplyMapping={csv.applyMapping}
                onRetry={csv.retryMetrics}
              />
            </div>
          ),
          trends: (
            <TrendsSection
              state={analysis.trends}
              columns={summary.columns}
              options={analysis.trendsRequest.options}
              onChangeOptions={csv.changeTrendOptions}
              onRetry={csv.retryTrends}
            />
          ),
          products: (
            <PerformanceSection
              state={analysis.performance}
              columns={summary.columns}
              options={analysis.performanceRequest.options}
              onChangeOptions={csv.changePerformanceOptions}
              onRetry={csv.retryPerformance}
            />
          ),
          quality: <QualitySection state={analysis.profile} onRetry={csv.retryProfile} />,
        }}
      />
    </>
  )
}

function PageIntro() {
  return (
    <section className="intro">
      <h1>Analytics</h1>
      <p>Key findings, numbers, trends, product rankings, and data quality for the file you analyze.</p>
    </section>
  )
}
