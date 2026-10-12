// The real requests of an analysis and their state. No percentages: the browser's
// fetch API cannot report upload progress, and server-side work has no progress signal.

import type { Analysis } from '../hooks/useCsvAnalysis'
import type { RequestState } from '../lib/requestState'
import { CheckIcon, ErrorIcon, MinusIcon, PendingIcon, Spinner } from './Icons'

type StepStatus = 'pending' | 'running' | 'done' | 'failed' | 'skipped'

const STATUS_TEXT: Record<StepStatus, string> = {
  pending: 'Waiting',
  running: 'In progress',
  done: 'Done',
  failed: 'Failed',
  skipped: 'Not run',
}

function stepStatus(state: RequestState<unknown>): StepStatus {
  switch (state.status) {
    case 'idle':
      return 'pending'
    case 'loading':
      return 'running'
    case 'success':
      return 'done'
    case 'error':
      return 'failed'
  }
}

function StepIcon({ status }: { status: StepStatus }) {
  switch (status) {
    case 'running':
      return <Spinner className="step-icon" />
    case 'done':
      return <CheckIcon size={18} className="step-icon tone-icon tone-good" />
    case 'failed':
      return <ErrorIcon size={18} className="step-icon tone-icon tone-critical" />
    case 'skipped':
      return <MinusIcon size={18} className="step-icon" />
    case 'pending':
      return <PendingIcon size={18} className="step-icon" />
  }
}

export function AnalysisSteps({ analysis }: { analysis: Analysis }) {
  const validationFailed = analysis.validation.status === 'error'
  const later = (state: RequestState<unknown>): StepStatus => (validationFailed ? 'skipped' : stepStatus(state))
  const steps = [
    {
      id: 'validate',
      label: analysis.mode === 'library' ? 'Validate and save the file' : 'Validate the file',
      status: stepStatus(analysis.validation),
    },
    { id: 'profile', label: 'Profile data quality', status: later(analysis.profile) },
    { id: 'metrics', label: 'Calculate retail metrics', status: later(analysis.metrics) },
    { id: 'trends', label: 'Calculate sales trends', status: later(analysis.trends) },
    { id: 'performance', label: 'Rank products and categories', status: later(analysis.performance) },
  ]

  return (
    <div className="analysis-steps">
      <ol className="steps" aria-label="Analysis steps">
        {steps.map((step) => (
          <li key={step.id} className={`step step-${step.status}`}>
            <StepIcon status={step.status} />
            <span className="step-label">{step.label}</span>
            <span className="step-status">{STATUS_TEXT[step.status]}</span>
          </li>
        ))}
      </ol>
      <p className="sr-only" role="status">
        {summarize(steps)}
      </p>
    </div>
  )
}

function summarize(steps: { label: string; status: StepStatus }[]): string {
  const running = steps.find((step) => step.status === 'running')
  if (running) return `${running.label}: in progress.`
  const failed = steps.filter((step) => step.status === 'failed').length
  if (failed > 0) return `Analysis finished. ${failed} step${failed === 1 ? '' : 's'} failed.`
  if (steps.every((step) => step.status === 'done')) return 'Analysis complete.'
  return ''
}
