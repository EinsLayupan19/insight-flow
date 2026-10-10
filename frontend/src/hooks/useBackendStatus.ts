import { useEffect, useState } from 'react'
import { fetchHealth, type HealthResponse } from '../api/health'

export type BackendStatus =
  | { kind: 'checking' }
  | { kind: 'connected'; health: HealthResponse }
  | { kind: 'error'; message: string }

// Checks the backend once on load, and again whenever `retry` is called.
export function useBackendStatus() {
  const [status, setStatus] = useState<BackendStatus>({ kind: 'checking' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false // ignore late results if the component unmounts

    fetchHealth().then(
      (health) => {
        if (!cancelled) setStatus({ kind: 'connected', health })
      },
      (error: unknown) => {
        console.error('Backend health check failed:', error)
        const message = error instanceof Error ? error.message : 'Unknown error while checking the backend.'
        if (!cancelled) setStatus({ kind: 'error', message })
      },
    )

    return () => {
      cancelled = true
    }
  }, [attempt])

  const retry = () => {
    setStatus({ kind: 'checking' })
    setAttempt((n) => n + 1)
  }

  return { status, retry }
}
