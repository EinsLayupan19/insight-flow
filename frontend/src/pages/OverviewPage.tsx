import { ConnectionAlert } from '../components/ConnectionStatus'
import { FileRequirements } from '../components/FileRequirements'
import { OverviewSummary } from '../components/OverviewSummary'
import { UploadPanel } from '../components/UploadPanel'
import type { BackendStatus } from '../hooks/useBackendStatus'
import type { CsvAnalysisController } from '../hooks/useCsvAnalysis'
import { routeHref } from '../lib/route'
import type { AnalyticsTab } from '../lib/tabs'

type OverviewPageProps = {
  csv: CsvAnalysisController
  backend: { status: BackendStatus; retry: () => void }
  onOpenAnalytics: (tab: AnalyticsTab) => void
}

/** Upload a file, follow its progress, and see the short answer. The analysis lives in App, so it survives page switches. */
export function OverviewPage({ csv, backend, onOpenAnalytics }: OverviewPageProps) {
  const hasResults = csv.analysis?.validation.status === 'success'

  return (
    <>
      <section className="intro">
        <h1>Overview</h1>
        <p>Upload a sales CSV to see its key numbers, how clean the data is, and what stands out.</p>
      </section>

      <ConnectionAlert status={backend.status} onRetry={backend.retry} />

      <div className={hasResults ? 'overview has-results' : 'overview'}>
        <UploadPanel
          selection={csv.selection}
          analysis={csv.analysis}
          saveToLibrary={csv.saveToLibrary}
          onSaveToLibraryChange={csv.setSaveToLibrary}
          onSelectFiles={csv.selectFiles}
          onClearSelection={csv.clearSelection}
          onAnalyze={csv.analyze}
          onRetry={csv.retryAnalysis}
          onCancel={csv.clearResults}
        >
          <FileRequirements />
          <p className="upload-footer small muted">
            Looking for an earlier file? <a href={routeHref({ page: 'datasets' })}>Open your datasets</a>.
          </p>
        </UploadPanel>

        {csv.analysis && (
          <OverviewSummary
            analysis={csv.analysis}
            onOpenAnalytics={onOpenAnalytics}
            onRetryMetrics={csv.retryMetrics}
            onRetryProfile={csv.retryProfile}
            onRetryInsights={csv.retryInsights}
            onClear={csv.clearResults}
          />
        )}
      </div>
    </>
  )
}
