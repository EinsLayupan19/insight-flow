import { useState } from 'react'
import { AppNav } from './components/AppNav'
import { ConnectionFooter } from './components/ConnectionStatus'
import { useBackendStatus } from './hooks/useBackendStatus'
import { useCsvAnalysis } from './hooks/useCsvAnalysis'
import { usePageChangeFocus, useRoute } from './hooks/useRoute'
import type { AnalyticsTab } from './lib/tabs'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { DatasetDetailPage } from './pages/DatasetDetailPage'
import { DatasetsPage } from './pages/DatasetsPage'
import { OverviewPage } from './pages/OverviewPage'

const MAIN_ID = 'main-content'

function App() {
  const route = useRoute()
  // Lives here, not in a page, so the current results survive switching pages.
  const csv = useCsvAnalysis()
  // One health check for the whole app: the footer shows it, the Overview explains a failure.
  const backend = useBackendStatus()
  // Kept here so the Overview can open a specific Analytics tab, and the tab survives page switches.
  const [analyticsTab, setAnalyticsTab] = useState<AnalyticsTab>('summary')
  const [notice, setNotice] = useState<string | null>(null)
  const [noticePage, setNoticePage] = useState(route.page)
  usePageChangeFocus(route, MAIN_ID)

  // A notice (such as "Deleted ...") is shown on the datasets list; drop it once the user moves on.
  if (route.page !== noticePage) {
    setNoticePage(route.page)
    if (route.page !== 'datasets') setNotice(null)
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <img src="/favicon.svg" alt="" width="28" height="28" />
          <span>InsightFlow AI</span>
        </div>
        <AppNav route={route} />
      </header>

      <main id={MAIN_ID} className="content" tabIndex={-1}>
        {route.page === 'overview' && <OverviewPage csv={csv} backend={backend} onOpenAnalytics={setAnalyticsTab} />}
        {route.page === 'analytics' && <AnalyticsPage csv={csv} tab={analyticsTab} onTabChange={setAnalyticsTab} />}
        {route.page === 'datasets' && <DatasetsPage notice={notice} onDismissNotice={() => setNotice(null)} />}
        {route.page === 'dataset' && (
          <DatasetDetailPage
            key={route.datasetId}
            datasetId={route.datasetId}
            analysisId={route.analysisId}
            onDeleted={setNotice}
          />
        )}
      </main>

      <footer className="app-footer">
        <p>InsightFlow AI. Files are stored only when you save them to your datasets.</p>
        <ConnectionFooter status={backend.status} onRetry={backend.retry} />
      </footer>
    </div>
  )
}

export default App
