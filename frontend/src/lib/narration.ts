// Wording for the optional AI summary. The summary text itself always comes from the API.

import type { NarrationRecord, NarratorStatus } from '../api/narration'
import { formatDateTime } from './format'

export type NarratorView = { kind: 'hidden' } | { kind: 'unavailable'; message: string } | { kind: 'ready'; model: string }

/** Nothing is shown unless a narrator is configured: the findings never need it. */
export function narratorView(status: NarratorStatus | null): NarratorView {
  if (status === null || !status.enabled) return { kind: 'hidden' }
  if (!status.available) return { kind: 'unavailable', message: status.reason ?? 'The narrator is not available.' }
  return { kind: 'ready', model: status.model ?? 'the local model' }
}

export type NarrationDescription = { heading: string; detail: string; problems: string[] }

export function describeNarration(record: NarrationRecord, timeZone?: string): NarrationDescription {
  const when = formatDateTime(record.created_at, timeZone)
  const by = `${record.model} (${record.provider}) with prompt ${record.prompt_version} on ${when}`
  switch (record.status) {
    case 'accepted':
      return {
        heading: 'AI-written summary of the findings below',
        detail: `Written by ${by}. Every number and quoted name was checked against the findings.`,
        problems: [],
      }
    case 'rejected':
      return {
        heading: 'Template summary: the AI summary did not pass the checks',
        detail: `Asked ${by}. Its text was not shown.`,
        problems: record.problems,
      }
    case 'failed':
      return {
        heading: 'Template summary: the narrator did not answer',
        detail: `Asked ${by}.`,
        problems: record.problems,
      }
  }
}
