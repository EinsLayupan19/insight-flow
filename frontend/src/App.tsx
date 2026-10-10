import { BackendStatus } from './components/BackendStatus'

// Planned capabilities, shown as a roadmap only. No analytics data exists yet.
const ROADMAP = [
  { title: 'Data import & quality checks', detail: 'Upload retail CSV files and validate them before analysis.' },
  { title: 'Profitability analysis', detail: 'Margins, revenue, and KPIs calculated with DuckDB.' },
  { title: 'Change investigations', detail: 'Explain what changed between periods, backed by evidence.' },
  { title: 'Ask in plain English', detail: 'Natural-language questions answered with verifiable SQL.' },
]

function App() {
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
          <h1>Welcome to InsightFlow AI</h1>
          <p>
            Import retail data, check its quality, and investigate profitability with answers you can verify.
          </p>
        </section>

        <BackendStatus />

        <section className="card" aria-labelledby="roadmap-heading">
          <div className="card-header">
            <h2 id="roadmap-heading">Getting started</h2>
          </div>
          <p className="empty-state">No data has been imported yet. Data upload arrives in the next phase.</p>
          <ul className="roadmap">
            {ROADMAP.map((item) => (
              <li key={item.title}>
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.detail}</p>
                </div>
                <span className="badge">Planned</span>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="app-footer">Phase 1 · Project foundation</footer>
    </div>
  )
}

export default App
