import { useState } from 'react'
import type {
  AnalysisRecord,
  AnalysisSummary,
  DatasetDetail,
  InsightsAnalysisRecord,
  PerformanceAnalysisRecord,
  TrendsAnalysisRecord,
} from '../api/datasets'
import { ColumnMappingPanel } from '../components/ColumnMappingPanel'
import { Callout, LoadingState, StatusBadge } from '../components/Feedback'
import { Spinner } from '../components/Icons'
import { MetricsView } from '../components/MetricsReport'
import { KeyFindingsView } from '../components/KeyFindings'
import { NarrationPanel } from '../components/NarrationPanel'
import { PerformanceView } from '../components/PerformanceReport'
import { QualityReportView } from '../components/QualityReport'
import { TrendsView } from '../components/TrendsReport'
import { useDatasetDetail, type AnalysisRun, type DatasetAction } from '../hooks/useDatasets'
import { navigate } from '../hooks/useRoute'
import { explicitMapping, type ColumnMapping } from '../lib/columnMapping'
import { ANALYSIS_TITLES, describeHighlights, describeMapping, shortHash } from '../lib/datasetDisplay'
import { formatBytes, formatDateTime, pluralize } from '../lib/format'
import { hasUnavailableMetrics } from '../lib/metricDisplay'
import { latestData, type RequestState } from '../lib/requestState'
import { datasetHref, routeHref } from '../lib/route'
import { DEFAULT_INSIGHT_OPTIONS, type InsightOptions } from '../lib/insights'
import { DEFAULT_PERFORMANCE_OPTIONS, type PerformanceOptions } from '../lib/performance'
import { DEFAULT_TREND_OPTIONS, GRAINS, GRAIN_LABELS, type TrendOptions } from '../lib/trends'

type DatasetDetailPageProps = {
  datasetId: number
  analysisId: number | null
  onDeleted: (message: string) => void
}

const RUNNING_TEXT: Record<DatasetAction, string> = {
  profile: 'Running a data-quality check on the stored file…',
  metrics: 'Calculating retail metrics from the stored file…',
  trends: 'Calculating sales trends from the stored file…',
  performance: 'Ranking products and categories in the stored file…',
  insights: 'Finding key insights in the stored file…',
  delete: 'Deleting the dataset…',
}

/** One saved dataset: its stored file, its analysis history, and any recorded result. Mount with key={datasetId}. */
export function DatasetDetailPage({ datasetId, analysisId, onDeleted }: DatasetDetailPageProps) {
  const detail = useDatasetDetail(datasetId, analysisId)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const dataset = latestData(detail.dataset)
  const analyses = latestData(detail.analyses)

  if (dataset === null) {
    return (
      <>
        <BackLink />
        {detail.dataset.status === 'error' ? (
          <>
            <section className="intro">
              <h1>Dataset not available</h1>
            </section>
            <Callout
              tone="critical"
              action={
                <>
                  <button type="button" className="button-secondary" onClick={detail.reload}>
                    Try again
                  </button>
                  <a className="button-ghost" href={routeHref({ page: 'datasets' })}>
                    Back to saved datasets
                  </a>
                </>
              }
            >
              {detail.dataset.message}
            </Callout>
          </>
        ) : (
          <LoadingState>Loading the dataset…</LoadingState>
        )}
      </>
    )
  }

  const busy = detail.running !== null
  const canAnalyze = !busy && dataset.file_stored

  const run = async (analysisRun: AnalysisRun) => {
    const record = await detail.runAnalysis(analysisRun)
    if (record) navigate(datasetHref(datasetId, record.id))
  }

  const remove = async () => {
    const recorded = pluralize(dataset.analysis_count, 'recorded analysis', 'recorded analyses')
    if (await detail.remove()) {
      onDeleted(`Deleted “${dataset.filename}”. Its stored file and ${recorded} were removed from the server.`)
      navigate(routeHref({ page: 'datasets' }))
    }
  }

  return (
    <>
      <BackLink />

      <section className="card dataset-header" aria-labelledby="dataset-heading">
        <div className="dataset-heading-row">
          <div className="results-title">
            <p className="eyebrow">Saved dataset #{dataset.id}</p>
            <h1 id="dataset-heading">{dataset.filename}</h1>
            <p className="results-meta">
              {pluralize(dataset.row_count, 'row')} · {pluralize(dataset.column_count, 'column')} ·{' '}
              {formatBytes(dataset.size_bytes)} · saved {formatDateTime(dataset.created_at)}
            </p>
          </div>
          <div className="dataset-actions">
            <button type="button" className="button-primary" disabled={!canAnalyze} onClick={() => void run({ kind: 'profile' })}>
              Run data-quality check
            </button>
            <button type="button" className="button-secondary" disabled={!canAnalyze} onClick={() => void run({ kind: 'metrics', mapping: {} })}>
              Calculate metrics
            </button>
            <button type="button" className="button-secondary" disabled={!canAnalyze} onClick={() => void run({ kind: 'trends', mapping: {}, options: DEFAULT_TREND_OPTIONS })}
            >
              Calculate trends
            </button>
            <button
              type="button"
              className="button-secondary"
              disabled={!canAnalyze}
              onClick={() => void run({ kind: 'performance', mapping: {}, options: DEFAULT_PERFORMANCE_OPTIONS })}
            >
              Rank products
            </button>
            <button
              type="button"
              className="button-secondary"
              disabled={!canAnalyze}
              onClick={() => void run({ kind: 'insights', mapping: {}, options: DEFAULT_INSIGHT_OPTIONS })}
            >
              Find insights
            </button>
            <button type="button" className="button-ghost danger" disabled={busy} onClick={() => setConfirmingDelete(true)}>
              Delete dataset
            </button>
          </div>
        </div>

        <dl className="dataset-facts">
          <div>
            <dt>Stored file</dt>
            <dd>
              {dataset.file_stored ? (
                <StatusBadge tone="good">On the server's disk</StatusBadge>
              ) : (
                <StatusBadge tone="critical">Missing or changed</StatusBadge>
              )}
            </dd>
          </div>
          <div>
            <dt>SHA-256</dt>
            <dd>
              <code title={dataset.sha256}>{shortHash(dataset.sha256)}…</code>
            </dd>
          </div>
          <div className="dataset-columns">
            <dt>Columns</dt>
            <dd>
              <ul className="chip-list">
                {dataset.columns.map((column) => (
                  <li key={column}>
                    <code>{column}</code>
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        </dl>

        {!dataset.file_stored && (
          <Callout tone="critical" title="The stored file is missing or has changed">
            New analyses can't run on this dataset. Its recorded results below are still available. To analyze the file
            again, delete this dataset and save the file again.
          </Callout>
        )}

        {confirmingDelete && (
          <DeleteConfirmation
            dataset={dataset}
            busy={busy}
            onConfirm={() => void remove()}
            onCancel={() => setConfirmingDelete(false)}
          />
        )}

        {detail.running && (
          <p className="updating-note action-note" role="status">
            <Spinner /> {RUNNING_TEXT[detail.running]}
          </p>
        )}
        {detail.actionError && <Callout tone="critical">{detail.actionError}</Callout>}
      </section>

      <section className="card" aria-labelledby="history-heading" aria-busy={detail.analyses.status === 'loading'}>
        <div className="card-header">
          <h2 id="history-heading">Analysis history{analyses ? ` (${analyses.length})` : ''}</h2>
        </div>
        {detail.analyses.status === 'error' && (
          <Callout
            tone="critical"
            title="The history could not be loaded"
            action={
              <button type="button" className="button-secondary" onClick={detail.reload}>
                Try again
              </button>
            }
          >
            {detail.analyses.message}
          </Callout>
        )}
        {analyses === null ? (
          detail.analyses.status === 'loading' && <LoadingState>Loading the history…</LoadingState>
        ) : analyses.length === 0 ? (
          <p className="empty-state">
            No analyses recorded yet. Run a data-quality check, calculate metrics or trends, rank products, or find
            insights to start the history.
          </p>
        ) : (
          <HistoryList datasetId={dataset.id} analyses={analyses} selectedId={detail.selectedId} />
        )}
      </section>

      {detail.selectedId !== null && (
        <AnalysisViewer
          record={detail.record}
          dataset={dataset}
          busy={busy}
          onApplyMapping={(mapping) => void run({ kind: 'metrics', mapping })}
          onRunTrends={(mapping, options) => void run({ kind: 'trends', mapping, options })}
          onRunPerformance={(mapping, options) => void run({ kind: 'performance', mapping, options })}
          onRunInsights={(mapping, options) => void run({ kind: 'insights', mapping, options })}
          onRetry={detail.reload}
        />
      )}
    </>
  )
}

function BackLink() {
  return (
    <p className="back-link">
      <a href={routeHref({ page: 'datasets' })}>← All saved datasets</a>
    </p>
  )
}

type DeleteConfirmationProps = {
  dataset: DatasetDetail
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
}

function DeleteConfirmation({ dataset, busy, onConfirm, onCancel }: DeleteConfirmationProps) {
  return (
    <div className="confirm-panel" role="group" aria-labelledby="confirm-delete-title">
      <p id="confirm-delete-title" className="callout-title">
        Delete “{dataset.filename}”?
      </p>
      <p>
        This permanently removes the stored file from the server's disk and its{' '}
        {pluralize(dataset.analysis_count, 'recorded analysis', 'recorded analyses')} from the database. It can't be
        undone.
      </p>
      <div className="callout-action">
        <button type="button" className="button-danger" disabled={busy} onClick={onConfirm}>
          Delete permanently
        </button>
        {/* Cancel takes focus first, so pressing Enter by habit does not delete anything. */}
        <button type="button" className="button-secondary" disabled={busy} onClick={onCancel} autoFocus>
          Cancel
        </button>
      </div>
    </div>
  )
}

function HistoryList({ datasetId, analyses, selectedId }: { datasetId: number; analyses: AnalysisSummary[]; selectedId: number | null }) {
  return (
    <ol className="history-list">
      {analyses.map((analysis) => {
        const selected = analysis.id === selectedId
        return (
          <li key={analysis.id}>
            <a
              className={selected ? 'history-item is-selected' : 'history-item'}
              href={datasetHref(datasetId, analysis.id)}
              aria-current={selected ? 'true' : undefined}
            >
              <span className="history-kind">{ANALYSIS_TITLES[analysis.kind]}</span>
              <span className="history-detail">
                {describeHighlights(analysis)}
                {analysis.kind !== 'profile' && ` · ${describeMapping(analysis.column_mapping)}`}
              </span>
              <span className="history-time">
                #{analysis.id} · <time dateTime={analysis.created_at}>{formatDateTime(analysis.created_at)}</time>
              </span>
            </a>
          </li>
        )
      })}
    </ol>
  )
}

type AnalysisViewerProps = {
  record: RequestState<AnalysisRecord>
  dataset: DatasetDetail
  busy: boolean
  onApplyMapping: (mapping: ColumnMapping) => void
  onRunTrends: (mapping: ColumnMapping, options: TrendOptions) => void
  onRunPerformance: (mapping: ColumnMapping, options: PerformanceOptions) => void
  onRunInsights: (mapping: ColumnMapping, options: InsightOptions) => void
  onRetry: () => void
}

/** A recorded result, exactly as stored. Changing the mapping records a new analysis; it never edits this one. */
function AnalysisViewer({
  record,
  dataset,
  busy,
  onApplyMapping,
  onRunTrends,
  onRunPerformance,
  onRunInsights,
  onRetry,
}: AnalysisViewerProps) {
  const data = latestData(record)
  return (
    <section className="card section-card" aria-labelledby="viewer-heading" aria-busy={record.status === 'loading'}>
      <header className="section-header">
        <p className="eyebrow">Recorded analysis{data ? ` #${data.id}` : ''}</p>
        <h2 id="viewer-heading">{data ? ANALYSIS_TITLES[data.kind] : 'Recorded analysis'}</h2>
        {data && (
          <p>
            Ran {formatDateTime(data.created_at)} with InsightFlow {data.app_version}. These are the results exactly as
            they were recorded.
          </p>
        )}
      </header>

      {record.status === 'error' && (
        <Callout
          tone="critical"
          title="This analysis could not be loaded"
          action={
            <button type="button" className="button-secondary" onClick={onRetry}>
              Try again
            </button>
          }
        >
          {record.message}
        </Callout>
      )}

      {data === null ? (
        record.status === 'loading' && <LoadingState>Loading the recorded results…</LoadingState>
      ) : data.kind === 'profile' ? (
        <QualityReportView report={data.result} />
      ) : data.kind === 'trends' ? (
        <RecordedTrends record={data} dataset={dataset} disabled={busy || !dataset.file_stored} onRun={onRunTrends} />
      ) : data.kind === 'insights' ? (
        <RecordedInsights record={data} disabled={busy || !dataset.file_stored} onRun={onRunInsights} />
      ) : data.kind === 'performance' ? (
        <RecordedPerformance record={data} dataset={dataset} disabled={busy || !dataset.file_stored} onRun={onRunPerformance} />
      ) : (
        <>
          <ColumnMappingPanel
            columns={dataset.columns}
            applied={data.column_mapping}
            used={data.result.columns_used}
            busy={busy || !dataset.file_stored}
            showHint={hasUnavailableMetrics(data.result)}
            onApply={onApplyMapping}
          />
          <MetricsView metrics={data.result} />
        </>
      )}
    </section>
  )
}

type RecordedTrendsProps = {
  record: TrendsAnalysisRecord
  dataset: DatasetDetail
  disabled: boolean
  onRun: (mapping: ColumnMapping, options: TrendOptions) => void
}

/** Recorded trends. A different grain, date column, or column choice records a new trends analysis. */
function RecordedTrends({ record, dataset, disabled, onRun }: RecordedTrendsProps) {
  const mapping = explicitMapping(record.column_mapping) // the metrics roles; the date column is an option
  const options: TrendOptions = { grain: record.grain, dateColumn: record.column_mapping.order_date ?? '' }
  const { result } = record
  return (
    <>
      <ColumnMappingPanel
        columns={dataset.columns}
        applied={mapping}
        used={result.columns_used}
        busy={disabled}
        showHint={result.revenue.status !== 'calculated' || result.order_count.status !== 'calculated'}
        onApply={(choices) => onRun(choices, options)}
      />
      <TrendsView
        trends={result}
        columns={dataset.columns}
        options={options}
        busy={false}
        disabled={disabled}
        onChangeOptions={(next) => onRun(mapping, next)}
      />
    </>
  )
}

type RecordedPerformanceProps = {
  record: PerformanceAnalysisRecord
  dataset: DatasetDetail
  disabled: boolean
  onRun: (mapping: ColumnMapping, options: PerformanceOptions) => void
}

/** Recorded rankings. A different label column or column choice records a new performance analysis. */
function RecordedPerformance({ record, dataset, disabled, onRun }: RecordedPerformanceProps) {
  const mapping = explicitMapping(record.column_mapping) // the metrics roles; label columns are options
  const options: PerformanceOptions = {
    productColumn: record.column_mapping.product ?? '',
    categoryColumn: record.column_mapping.category ?? '',
  }
  const { products } = record.result
  return (
    <>
      <ColumnMappingPanel
        columns={dataset.columns}
        applied={mapping}
        used={record.result.columns_used}
        busy={disabled}
        showHint={products.status === 'calculated' && products.revenue.status !== 'calculated'}
        onApply={(choices) => onRun(choices, options)}
      />
      <PerformanceView
        performance={record.result}
        columns={dataset.columns}
        options={options}
        busy={false}
        disabled={disabled}
        onChangeOptions={(next) => onRun(mapping, next)}
      />
    </>
  )
}

type RecordedInsightsProps = {
  record: InsightsAnalysisRecord
  disabled: boolean
  onRun: (mapping: ColumnMapping, options: InsightOptions) => void
}

/** Recorded findings. Comparing by another period records a new insights analysis with the same columns. */
function RecordedInsights({ record, disabled, onRun }: RecordedInsightsProps) {
  const mapping = explicitMapping(record.column_mapping)
  const options: InsightOptions = {
    grain: record.grain,
    dateColumn: record.column_mapping.order_date ?? '',
    productColumn: record.column_mapping.product ?? '',
    categoryColumn: record.column_mapping.category ?? '',
  }
  return (
    <KeyFindingsView insights={record.result} busy={false}>
      <NarrationPanel key={record.id} datasetId={record.dataset_id} analysisId={record.id} disabled={disabled} />
      <div className="trend-controls">
        <fieldset className="field">
          <legend>Compare by</legend>
          <div className="segmented">
            {GRAINS.map((grain) => (
              <label key={grain} className="segment">
                <input
                  type="radio"
                  name="insights-grain"
                  value={grain}
                  checked={grain === record.grain}
                  disabled={disabled}
                  onChange={() => onRun(mapping, { ...options, grain })}
                />
                <span>{GRAIN_LABELS[grain]}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>
    </KeyFindingsView>
  )
}
