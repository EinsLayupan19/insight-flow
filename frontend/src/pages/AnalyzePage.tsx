import { AnalysisResults } from '../components/AnalysisResults'
import { BackendStatus } from '../components/BackendStatus'
import { UploadPanel } from '../components/UploadPanel'
import { WorkflowGuide } from '../components/WorkflowGuide'
import type { CsvAnalysisController } from '../hooks/useCsvAnalysis'

/** Upload a file and see its results. The analysis state lives in App, so it survives page switches. */
export function AnalyzePage({ csv }: { csv: CsvAnalysisController }) {
  return (
    <>
      <section className="intro">
        <h1>Retail CSV analysis</h1>
        <p>
          Upload a sales file to check its data quality, see the retail metrics its columns support, follow sales over
          time, and rank products and categories. Every number shows how it was calculated.
        </p>
      </section>

      {/* Source order: upload, results, sidebar. CSS moves the sidebar beside the upload card on wide screens. */}
      <div className="workspace">
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
        />

        {csv.analysis && (
          <AnalysisResults
            analysis={csv.analysis}
            onRetryProfile={csv.retryProfile}
            onRetryMetrics={csv.retryMetrics}
            onRetryTrends={csv.retryTrends}
            onRetryPerformance={csv.retryPerformance}
            onApplyMapping={csv.applyMapping}
            onChangeTrendOptions={csv.changeTrendOptions}
            onChangePerformanceOptions={csv.changePerformanceOptions}
            onClear={csv.clearResults}
          />
        )}

        <aside className="sidebar" aria-label="About this tool">
          <WorkflowGuide />
          <BackendStatus />
        </aside>
      </div>
    </>
  )
}
