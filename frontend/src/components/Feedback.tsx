// Shared status UI. Status colors never carry meaning alone: each comes with an icon and text.

import type { ReactNode } from 'react'
import { AlertIcon, CheckIcon, ErrorIcon, InfoIcon, MinusIcon, Spinner } from './Icons'

export type Tone = 'good' | 'warning' | 'critical' | 'neutral' | 'info'

const ICONS = {
  good: CheckIcon,
  warning: AlertIcon,
  critical: ErrorIcon,
  neutral: MinusIcon,
  info: InfoIcon,
} as const

export function StatusBadge({ tone, children }: { tone: Tone; children: ReactNode }) {
  const Icon = ICONS[tone]
  return (
    <span className={`status-badge tone-${tone}`}>
      <Icon size={14} className="tone-icon" />
      {children}
    </span>
  )
}

type CalloutProps = {
  tone: Tone
  title?: string
  children: ReactNode
  action?: ReactNode
}

/** A message block. Critical callouts are announced to screen readers immediately. */
export function Callout({ tone, title, children, action }: CalloutProps) {
  const Icon = ICONS[tone]
  return (
    <div className={`callout tone-${tone}`} role={tone === 'critical' ? 'alert' : undefined}>
      <Icon size={18} className="tone-icon callout-icon" />
      <div className="callout-body">
        {title && <p className="callout-title">{title}</p>}
        <div className="callout-text">{children}</div>
        {action && <div className="callout-action">{action}</div>}
      </div>
    </div>
  )
}

export function LoadingState({ children }: { children: ReactNode }) {
  return (
    <div className="loading-state" role="status">
      <Spinner />
      <span>{children}</span>
    </div>
  )
}
