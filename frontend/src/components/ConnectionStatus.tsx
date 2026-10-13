// Connection to the InsightFlow server. A quiet line in the footer while all is well; a full
// message (with "Check again") on the Overview when the server cannot be reached.

import type { BackendStatus } from '../hooks/useBackendStatus'
import { Callout } from './Feedback'

const LABELS = {
  checking: 'Checking the connection…',
  connected: 'Connected to the server',
  error: 'Not connected to the server',
} as const

type ConnectionProps = { status: BackendStatus; onRetry: () => void }

export function ConnectionFooter({ status, onRetry }: ConnectionProps) {
  return (
    <div className="connection-footer">
      <p className="status-row" role="status" aria-live="polite">
        <span className={`status-dot status-${status.kind}`} aria-hidden="true" />
        <span>{LABELS[status.kind]}</span>
        {status.kind === 'connected' && (
          <span className="muted">
            Version {status.health.version}, {status.health.environment}
          </span>
        )}
      </p>
      <button type="button" className="link-button" onClick={onRetry} disabled={status.kind === 'checking'}>
        Check again
      </button>
    </div>
  )
}

export function ConnectionAlert({ status, onRetry }: ConnectionProps) {
  if (status.kind !== 'error') return null
  return (
    <Callout
      tone="critical"
      title="The InsightFlow server cannot be reached"
      action={
        <button type="button" className="button-secondary" onClick={onRetry}>
          Check again
        </button>
      }
    >
      Files cannot be analyzed until it is back. {status.message}
    </Callout>
  )
}
