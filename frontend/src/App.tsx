import { useState } from 'react'
import { AppNav } from './components/AppNav'
import { useCsvAnalysis } from './hooks/useCsvAnalysis'
import { usePageChangeFocus, useRoute } from './hooks/useRoute'
import { AnalyzePage } from './pages/AnalyzePage'
import { DatasetDetailPage } from './pages/DatasetDetailPage'
import { DatasetsPage } from './pages/DatasetsPage'

const MAIN_ID = 'main-content'

function App() {
  const route = useRoute()
  // Lives here, not in AnalyzePage, so the current results survive switching pages.
  const csv = useCsvAnalysis()
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
        {route.page === 'analyze' && <AnalyzePage csv={csv} />}
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
        InsightFlow AI · Evidence-first retail analytics · Files are stored only when you save them to the dataset library
      </footer>
    </div>
  )
}

export default App
