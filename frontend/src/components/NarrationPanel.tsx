// The optional AI summary of saved key findings. Hidden unless a narrator is configured on the
// server. Text is shown as plain text and labelled: AI-written only when it passed every check,
// otherwise the template summary with the reason.

import { useCallback, useEffect, useRef, useState } from 'react'
import { createNarration, getNarratorStatus, listNarrations, type NarrationRecord, type NarratorStatus } from '../api/narration'
import { userMessage } from '../lib/errors'
import { describeNarration, narratorView } from '../lib/narration'
import { Notes } from './Evidence'
import { Callout } from './Feedback'
import { Spinner } from './Icons'

type NarrationPanelProps = { datasetId: number; analysisId: number; disabled: boolean }

export function NarrationPanel({ datasetId, analysisId, disabled }: NarrationPanelProps) {
  const [status, setStatus] = useState<NarratorStatus | null>(null)
  const [latest, setLatest] = useState<NarrationRecord | null>(null)
  const [writing, setWriting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)

  useEffect(() => {
    const load = new AbortController()
    getNarratorStatus(load.signal).then(setStatus, () => setStatus(null)) // no status: nothing is shown
    listNarrations(datasetId, analysisId, load.signal).then(
      (narrations) => setLatest(narrations[0] ?? null),
      () => setLatest(null),
    )
    return () => {
      load.abort()
      controller.current?.abort()
    }
  }, [datasetId, analysisId])

  const write = useCallback(async () => {
    controller.current?.abort()
    const request = new AbortController()
    controller.current = request
    setWriting(true)
    setError(null)
    try {
      setLatest(await createNarration(datasetId, analysisId, request.signal))
    } catch (failure) {
      if (!request.signal.aborted) setError(userMessage(failure))
    } finally {
      if (controller.current === request) setWriting(false)
    }
  }, [datasetId, analysisId])

  const cancel = () => {
    controller.current?.abort()
    setWriting(false)
  }

  const view = narratorView(status)
  if (view.kind === 'hidden' && latest === null) return null
  const description = latest ? describeNarration(latest) : null

  return (
    <div className="narration" aria-busy={writing}>
      <div className="narration-header">
        <h4 className="findings-subheading">Summary</h4>
        {view.kind === 'ready' && !writing && (
          <button type="button" className="button-secondary" disabled={disabled} onClick={() => void write()}>
            {latest ? 'Write a new summary' : 'Write a summary'}
          </button>
        )}
      </div>

      {view.kind === 'unavailable' && <p className="small muted">AI summaries are unavailable: {view.message}</p>}
      {writing && (
        <p className="updating-note" role="status">
          <Spinner /> Writing a summary with {view.kind === 'ready' ? view.model : 'the local model'} on this computer. This can
          take a minute.{' '}
          <button type="button" className="link-button" onClick={cancel}>
            Stop waiting
          </button>
        </p>
      )}
      {error && <Callout tone="critical">{error}</Callout>}

      {latest && description && (
        <figure className={latest.source === 'ai' ? 'narration-text is-ai' : 'narration-text'}>
          <figcaption className="narration-heading">{description.heading}</figcaption>
          <p>{latest.text}</p>
          <p className="small muted">{description.detail}</p>
          {description.problems.length > 0 && <Notes notes={description.problems} tone="info" />}
        </figure>
      )}
    </div>
  )
}
