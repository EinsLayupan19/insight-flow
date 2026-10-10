import type { Analysis } from '../hooks/useCsvAnalysis'
import type { ColumnMapping } from '../lib/columnMapping'
import { formatBytes, pluralize } from '../lib/format'
import { MetricsSection } from './MetricsReport'
import { QualitySection } from './QualityReport'

type AnalysisResultsProps = {
  analysis: Analysis
  onRetryProfile: () => void
  onRetryMetrics: () => void
  onApplyMapping: (mapping: ColumnMapping) => void
  onClear: () => void
}

/** Results of the latest analysis. Shown only after the file passed validation. */
export function AnalysisResults({ analysis, onRetryProfile, onRetryMetrics, onApplyMapping, onClear }: AnalysisResultsProps) {
  if (analysis.validation.status !== 'success') return null
  const summary = analysis.validation.data

  return (
    <section className="results" aria-labelledby="results-heading">
      <div className="results-header">
        <div className="results-title">
          <p className="eyebrow">Results</p>
          <h2 id="results-heading">{summary.filename}</h2>
          <p className="results-meta">
            {pluralize(summary.row_count, 'row')} · {pluralize(summary.column_count, 'column')} · {formatBytes(summary.size_bytes)}{' '}
            · analyzed in memory, not stored
          </p>
        </div>
        <div className="results-actions">
          <nav className="section-links" aria-label="Result sections">
            <a href="#data-quality">Data quality</a>
            <a href="#retail-metrics">Retail metrics</a>
          </nav>
          <button type="button" className="button-secondary" onClick={onClear}>
            Clear results
          </button>
        </div>
      </div>

      <QualitySection state={analysis.profile} onRetry={onRetryProfile} />
      <MetricsSection
        state={analysis.metrics}
        columns={summary.columns}
        appliedMapping={analysis.appliedMapping}
        onApplyMapping={onApplyMapping}
        onRetry={onRetryMetrics}
      />
    </section>
  )
}
