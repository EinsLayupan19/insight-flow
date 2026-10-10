import { AnalysisResults } from './components/AnalysisResults'
import { BackendStatus } from './components/BackendStatus'
import { UploadPanel } from './components/UploadPanel'
import { WorkflowGuide } from './components/WorkflowGuide'
import { useCsvAnalysis } from './hooks/useCsvAnalysis'

function App() {
  const csv = useCsvAnalysis()

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <img src="/favicon.svg" alt="" width="28" height="28" />
          <span>InsightFlow AI</span>
        </div>
        <span className="tagline">Evidence-first retail analytics</span>
      </header>

      <main className="content">
        <section className="intro">
          <h1>Retail CSV analysis</h1>
          <p>
            Upload a sales file to check its data quality and see the retail metrics its columns support. Every number
            shows how it was calculated.
          </p>
        </section>

        {/* Source order: upload, results, sidebar. CSS moves the sidebar beside the upload card on wide screens. */}
        <div className="workspace">
          <UploadPanel
            selection={csv.selection}
            analysis={csv.analysis}
            onSelectFiles={csv.selectFiles}
            onClearSelection={csv.clearSelection}
            onAnalyze={(file) => void csv.analyze(file)}
            onRetry={csv.retryAnalysis}
            onCancel={csv.clearResults}
          />

          {csv.analysis && (
            <AnalysisResults
              analysis={csv.analysis}
              onRetryProfile={csv.retryProfile}
              onRetryMetrics={csv.retryMetrics}
              onApplyMapping={csv.applyMapping}
              onClear={csv.clearResults}
            />
          )}

          <aside className="sidebar" aria-label="About this tool">
            <WorkflowGuide />
            <BackendStatus />
          </aside>
        </div>
      </main>

      <footer className="app-footer">InsightFlow AI · Files are analyzed in memory and not stored</footer>
    </div>
  )
}

export default App
