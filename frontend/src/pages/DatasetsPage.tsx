import type { DatasetSummary } from '../api/datasets'
import { Callout, LoadingState } from '../components/Feedback'
import { useDatasetList } from '../hooks/useDatasets'
import { formatBytes, formatCount, formatDateTime, pluralize } from '../lib/format'
import { latestData } from '../lib/requestState'
import { datasetHref, routeHref } from '../lib/route'

type DatasetsPageProps = {
  notice: string | null
  onDismissNotice: () => void
}

export function DatasetsPage({ notice, onDismissNotice }: DatasetsPageProps) {
  const { state, reload } = useDatasetList()
  const datasets = latestData(state)
  const loading = state.status === 'loading'

  return (
    <>
      <section className="intro">
        <h1>Datasets</h1>
        <p>Files you saved, each with the history of the analyses run on it.</p>
      </section>

      {notice && (
        <Callout
          tone="good"
          action={
            <button type="button" className="button-ghost" onClick={onDismissNotice}>
              Dismiss
            </button>
          }
        >
          {notice}
        </Callout>
      )}

      <section className="card" aria-labelledby="library-heading" aria-busy={loading}>
        <div className="card-header">
          <h2 id="library-heading">Saved files{datasets ? ` (${formatCount(datasets.length)})` : ''}</h2>
          <button type="button" className="button-secondary" onClick={reload} disabled={loading}>
            Refresh
          </button>
        </div>
        <p className="storage-note">
          Saved files and their analysis results are kept on the InsightFlow server until you delete them. Nothing is
          backed up or sent anywhere else.
        </p>

        {state.status === 'error' && (
          <Callout
            tone="critical"
            title="The saved datasets could not be loaded"
            action={
              <button type="button" className="button-secondary" onClick={reload}>
                Try again
              </button>
            }
          >
            {state.message}
          </Callout>
        )}

        {datasets === null ? (
          loading && <LoadingState>Loading saved datasets…</LoadingState>
        ) : datasets.length === 0 ? (
          <EmptyLibrary />
        ) : (
          <DatasetTable datasets={datasets} />
        )}
      </section>
    </>
  )
}

function EmptyLibrary() {
  return (
    <div className="empty-panel">
      <p className="empty-title">No saved datasets yet</p>
      <p>
        Upload a file on the Overview with <strong>Save to my datasets</strong> checked, and it appears here with its
        analysis history.
      </p>
      <a className="button-primary" href={routeHref({ page: 'overview' })}>
        Upload a file
      </a>
    </div>
  )
}

function DatasetTable({ datasets }: { datasets: DatasetSummary[] }) {
  return (
    <>
      <p className="table-hint small muted">Scroll the table sideways to see every column.</p>
      <div className="table-scroll" role="region" aria-labelledby="library-heading" tabIndex={0}>
        <table className="data-table dataset-table">
          <caption className="sr-only">Saved datasets, newest first</caption>
          <thead>
            <tr>
              <th scope="col">Dataset</th>
              <th scope="col" className="numeric">
                Rows
              </th>
              <th scope="col">Saved</th>
              <th scope="col">Analyses</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((dataset) => (
              <tr key={dataset.id}>
                <th scope="row">
                  <a className="dataset-link" href={datasetHref(dataset.id)}>
                    {dataset.filename}
                  </a>
                  <span className="dataset-id">
                    #{dataset.id}, {pluralize(dataset.column_count, 'column')}, {formatBytes(dataset.size_bytes)}
                  </span>
                </th>
                <td className="numeric num">{formatCount(dataset.row_count)}</td>
                <td>{formatDateTime(dataset.created_at)}</td>
                <td>
                  <span className="num">{formatCount(dataset.analysis_count)}</span>
                  <span className="dataset-id">
                    {dataset.last_analyzed_at ? `Last ${formatDateTime(dataset.last_analyzed_at)}` : 'None yet'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
