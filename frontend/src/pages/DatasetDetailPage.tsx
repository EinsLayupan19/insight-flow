import { useState } from 'react'
import type { AnalysisRecord, AnalysisSummary, DatasetDetail } from '../api/datasets'
import { ColumnMappingPanel } from '../components/ColumnMappingPanel'
import { Callout, LoadingState, StatusBadge } from '../components/Feedback'
import { Spinner } from '../components/Icons'
import { MetricsView } from '../components/MetricsReport'
import { QualityReportView } from '../components/QualityReport'
import { useDatasetDetail, type DatasetAction } from '../hooks/useDatasets'
import { navigate } from '../hooks/useRoute'
import type { ColumnMapping } from '../lib/columnMapping'
import { ANALYSIS_TITLES, describeHighlights, describeMapping, shortHash } from '../lib/datasetDisplay'
import { formatBytes, formatDateTime, pluralize } from '../lib/format'
import { hasUnavailableMetrics } from '../lib/metricDisplay'
import { latestData, type RequestState } from '../lib/requestState'
import { datasetHref, routeHref } from '../lib/route'

type DatasetDetailPageProps = {
  datasetId: number
  analysisId: number | null
  onDeleted: (message: string) => void
}

const RUNNING_TEXT: Record<DatasetAction, string> = {
  profile: 'Running a data-quality check on the stored file…',
  metrics: 'Calculating retail metrics from the stored file…',
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

  const run = async (kind: 'profile' | 'metrics', mapping?: ColumnMapping) => {
    const record = await detail.runAnalysis(kind, mapping)
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
            <button type="button" className="button-primary" disabled={!canAnalyze} onClick={() => void run('profile')}>
              Run data-quality check
            </button>
            <button type="button" className="button-secondary" disabled={!canAnalyze} onClick={() => void run('metrics')}>
              Calculate metrics
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
            No analyses recorded yet. Run a data-quality check or calculate metrics to start the history.
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
          onApplyMapping={(mapping) => void run('metrics', mapping)}
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
                {analysis.kind === 'metrics' && ` · ${describeMapping(analysis.column_mapping)}`}
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
  onRetry: () => void
}

/** A recorded result, exactly as stored. Changing the mapping records a new analysis; it never edits this one. */
function AnalysisViewer({ record, dataset, busy, onApplyMapping, onRetry }: AnalysisViewerProps) {
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
