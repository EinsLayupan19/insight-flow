// Key findings from the API: what the numbers show, most important first, each with the figures,
// periods, and rows behind it. Findings never state causes; "worth checking" items are questions,
// not findings. Checks that could not run are listed with their reasons.

import type { ReactNode } from 'react'
import type { Insight, SalesInsights } from '../api/uploads'
import { IMPORTANCE_LABELS, coverageText, evidenceRows, groupByImportance, summarizeFindings, thresholdLines } from '../lib/insights'
import { latestData, type RequestState } from '../lib/requestState'
import { Notes } from './Evidence'
import { Callout, LoadingState } from './Feedback'
import { Spinner } from './Icons'

type KeyFindingsSectionProps = {
  state: RequestState<SalesInsights>
  onRetry: () => void
}

/** The findings card on the analysis page. It follows the choices made in the other sections. */
export function KeyFindingsSection({ state, onRetry }: KeyFindingsSectionProps) {
  const data = latestData(state)
  const busy = state.status === 'loading'

  return (
    <section id="key-findings" className="card section-card" aria-labelledby="findings-heading" aria-busy={busy}>
      <header className="section-header">
        <h3 id="findings-heading">Key findings</h3>
        <p>What the numbers show, with the figures behind each finding. Findings describe; they never explain why.</p>
      </header>

      {state.status === 'error' && (
        <Callout
          tone="critical"
          title={data ? 'The findings could not be updated' : 'The findings could not be calculated'}
          action={
            <button type="button" className="button-secondary" onClick={onRetry}>
              Try again
            </button>
          }
        >
          {state.message}
          {data && ' The findings below are from the last successful calculation.'}
        </Callout>
      )}

      {data !== null ? (
        <KeyFindingsView insights={data} busy={busy}>
          <p className="small muted">
            Findings use the period and date column chosen in Sales trends, the columns chosen in Product &amp; category
            performance, and <strong>Map columns</strong> in Retail metrics.
          </p>
        </KeyFindingsView>
      ) : (
        state.status !== 'error' && <LoadingState>Finding key insights…</LoadingState>
      )}
    </section>
  )
}

type KeyFindingsViewProps = {
  insights: SalesInsights
  /** A new calculation is running: the findings shown are dimmed until it finishes. */
  busy: boolean
  children?: ReactNode
}

export function KeyFindingsView({ insights, busy, children }: KeyFindingsViewProps) {
  const groups = groupByImportance(insights.insights)
  return (
    <>
      {children}
      {busy && (
        <p className="updating-note" role="status">
          <Spinner /> Updating findings…
        </p>
      )}
      <div className={busy ? 'findings-body is-stale' : 'findings-body'}>
        <p className="metric-rows">
          {summarizeFindings(insights)} {coverageText(insights)}
        </p>

        {insights.caveats.length > 0 && (
          <div className="findings-caveats">
            <h4 className="findings-subheading">About this file</h4>
            <Notes notes={insights.caveats} tone="warning" />
          </div>
        )}

        {groups.length === 0 ? (
          <div className="empty-state trends-empty">
            <p className="empty-state-title">No findings to report</p>
            <p>The checks below could not run on this file, or found nothing that stands out.</p>
          </div>
        ) : (
          <ol className="findings-list">
            {groups.flatMap((group) => group.items).map((insight) => (
              <li key={insight.id}>
                <FindingCard insight={insight} insights={insights} />
              </li>
            ))}
          </ol>
        )}

        {insights.not_assessed.length > 0 && (
          <details className="disclosure" open={groups.length === 0}>
            <summary>Not assessed ({insights.not_assessed.length})</summary>
            <ul className="not-assessed">
              {insights.not_assessed.map((check) => (
                <li key={`${check.kind}-${check.title}`}>
                  <span className="not-assessed-title">{check.title}:</span> {check.reason}
                </li>
              ))}
            </ul>
          </details>
        )}

        <details className="disclosure">
          <summary>How findings are made</summary>
          <p>{insights.definition}</p>
          <ul className="evidence-list">
            {thresholdLines(insights.thresholds).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </details>
      </div>
    </>
  )
}

function FindingCard({ insight, insights }: { insight: Insight; insights: SalesInsights }) {
  const rows = evidenceRows(insight, insights)
  const headingId = `finding-${insight.id.replace(/[^a-z0-9-]/gi, '-')}`
  return (
    <article className={`finding finding-${insight.importance}`} aria-labelledby={headingId}>
      <p className="finding-importance">{IMPORTANCE_LABELS[insight.importance]}</p>
      <h4 id={headingId} className="finding-title">
        {insight.title}
      </h4>
      <p className="finding-statement">{insight.statement}</p>
      {insight.caveats.length > 0 && <Notes notes={insight.caveats} tone="warning" />}
      {insight.questions.length > 0 && (
        <div className="finding-questions">
          <p className="small muted">Worth checking (not a finding):</p>
          <ul>
            {insight.questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </div>
      )}
      {rows.length > 0 && (
        <details className="finding-evidence">
          <summary>Evidence</summary>
          <div className="table-scroll">
            <table className="data-table evidence-table">
              <thead>
                <tr>
                  <th scope="col">Figure</th>
                  <th scope="col" className="numeric">
                    Value
                  </th>
                  <th scope="col" className="numeric">
                    Before
                  </th>
                  <th scope="col" className="numeric">
                    Change
                  </th>
                  <th scope="col">Period</th>
                  <th scope="col">Compared with</th>
                  <th scope="col" className="numeric">
                    Rows
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => (
                  <tr key={index}>
                    <th scope="row">{row.metric}</th>
                    <td className="numeric num">{row.value ?? ''}</td>
                    <td className="numeric num">{row.previous ?? ''}</td>
                    <td className="numeric num">{row.change ?? ''}</td>
                    <td>{row.period ?? ''}</td>
                    <td>{row.comparison ?? ''}</td>
                    <td className="numeric num">{row.rows ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </article>
  )
}
