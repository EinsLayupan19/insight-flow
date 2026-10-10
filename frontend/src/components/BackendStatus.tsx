import { useBackendStatus } from '../hooks/useBackendStatus'

const LABELS = {
  checking: 'Checking connection…',
  connected: 'Connected',
  error: 'Not connected',
} as const

export function BackendStatus() {
  const { status, retry } = useBackendStatus()

  return (
    <section className="card" aria-labelledby="status-heading">
      <div className="card-header">
        <h2 id="status-heading">System status</h2>
        <button type="button" className="button-secondary" onClick={retry} disabled={status.kind === 'checking'}>
          Check again
        </button>
      </div>

      <div className="status-row" role="status" aria-live="polite">
        <span className={`status-dot status-${status.kind}`} aria-hidden="true" />
        <span className="status-name">Backend API</span>
        <span className="status-label">{LABELS[status.kind]}</span>
      </div>

      {status.kind === 'connected' && (
        <dl className="status-details">
          <div>
            <dt>Version</dt>
            <dd>{status.health.version}</dd>
          </div>
          <div>
            <dt>Environment</dt>
            <dd>{status.health.environment}</dd>
          </div>
        </dl>
      )}

      {status.kind === 'error' && <p className="callout-error">{status.message}</p>}
    </section>
  )
}
