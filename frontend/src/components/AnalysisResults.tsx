import type { SaveDatasetResponse } from '../api/datasets'
import type { Analysis } from '../hooks/useCsvAnalysis'
import type { ColumnMapping } from '../lib/columnMapping'
import { formatBytes, formatDateTime, pluralize } from '../lib/format'
import { datasetHref } from '../lib/route'
import { Callout } from './Feedback'
import { MetricsSection } from './MetricsReport'
import type { TrendOptions } from '../lib/trends'
import { QualitySection } from './QualityReport'
import { TrendsSection } from './TrendsReport'

type AnalysisResultsProps = {
  analysis: Analysis
  onRetryProfile: () => void
  onRetryMetrics: () => void
  onRetryTrends: () => void
  onApplyMapping: (mapping: ColumnMapping) => void
  onChangeTrendOptions: (options: TrendOptions) => void
  onClear: () => void
}

/** Results of the latest analysis. Shown only after the file passed validation. */
export function AnalysisResults({
  analysis,
  onRetryProfile,
  onRetryMetrics,
  onRetryTrends,
  onApplyMapping,
  onChangeTrendOptions,
  onClear,
}: AnalysisResultsProps) {
  if (analysis.validation.status !== 'success') return null
  const summary = analysis.validation.data

  return (
    <section className="results" aria-labelledby="results-heading">
      <div className="results-header">
        <div className="results-title">
          <p className="eyebrow">Results</p>
          <h2 id="results-heading">{analysis.file.name}</h2>
          <p className="results-meta">
            {pluralize(summary.row_count, 'row')} · {pluralize(summary.column_count, 'column')} · {formatBytes(summary.size_bytes)}
            {analysis.saved === null && ' · analyzed in memory, not stored'}
          </p>
        </div>
        <div className="results-actions">
          <div className="section-links" role="group" aria-label="Jump to a result section">
            <button type="button" className="link-button" onClick={() => scrollToSection('data-quality')}>
              Data quality
            </button>
            <button type="button" className="link-button" onClick={() => scrollToSection('retail-metrics')}>
              Retail metrics
            </button>
            <button type="button" className="link-button" onClick={() => scrollToSection('sales-trends')}>
              Sales trends
            </button>
          </div>
          <button type="button" className="button-secondary" onClick={onClear}>
            Clear results
          </button>
        </div>
      </div>

      {analysis.saved && <SavedNotice saved={analysis.saved} />}

      <QualitySection state={analysis.profile} onRetry={onRetryProfile} />
      <MetricsSection
        state={analysis.metrics}
        columns={summary.columns}
        appliedMapping={analysis.appliedMapping}
        onApplyMapping={onApplyMapping}
        onRetry={onRetryMetrics}
      />
      <TrendsSection
        state={analysis.trends}
        columns={summary.columns}
        options={analysis.trendsRequest.options}
        onChangeOptions={onChangeTrendOptions}
        onRetry={onRetryTrends}
      />
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
      <Callout tone="good" title="Saved to the dataset library" action={link}>
        The file is stored on the InsightFlow server as dataset #{dataset.id}. These results are recorded in its
        history.
      </Callout>
    )
  }
  return (
    <Callout tone="info" title="Already in the dataset library" action={link}>
      The same content was saved on {formatDateTime(dataset.created_at)} as “{dataset.filename}” (dataset #{dataset.id}).
      No second copy was stored; these results were added to that dataset's history.
    </Callout>
  )
}

function scrollToSection(id: string) {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  document.getElementById(id)?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' })
}
