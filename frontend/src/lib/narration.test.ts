import { describe, expect, it } from 'vitest'
import type { NarrationRecord, NarratorStatus } from '../api/narration'
import { describeNarration, narratorView } from './narration'

const READY: NarratorStatus = { enabled: true, provider: 'ollama', model: 'llama3.2:3b', available: true, reason: null }

function record(overrides: Partial<NarrationRecord> = {}): NarrationRecord {
  return {
    id: 1,
    dataset_id: 7,
    analysis_id: 3,
    created_at: '2026-10-12T09:00:00.000+00:00',
    provider: 'ollama',
    model: 'llama3.2:3b',
    prompt_version: 'narration-v1',
    status: 'accepted',
    source: 'ai',
    text: 'Revenue was 120.00 in March 2026.',
    problems: [],
    ...overrides,
  }
}

describe('narratorView', () => {
  it('hides everything when no narrator is configured, or while the status is unknown', () => {
    expect(narratorView({ ...READY, enabled: false, available: false, provider: null, model: null, reason: 'Off.' })).toEqual({ kind: 'hidden' })
    expect(narratorView(null)).toEqual({ kind: 'hidden' })
  })

  it('explains why a configured narrator is unavailable', () => {
    expect(narratorView({ ...READY, available: false, reason: 'Ollama is not running.' })).toEqual({
      kind: 'unavailable',
      message: 'Ollama is not running.',
    })
  })

  it('names the local model when ready', () => {
    expect(narratorView(READY)).toEqual({ kind: 'ready', model: 'llama3.2:3b' })
  })
})

describe('describeNarration', () => {
  it('labels accepted text as AI-written, with model and prompt version', () => {
    expect(describeNarration(record(), 'UTC')).toEqual({
      heading: 'AI-written summary of the findings below',
      detail: 'Written by llama3.2:3b (ollama) with prompt narration-v1 on Oct 12, 2026, 9:00 AM. Every number and quoted name was checked against the findings.',
      problems: [],
    })
  })

  it('says when the AI text failed the checks and the template is shown instead', () => {
    const rejected = record({ status: 'rejected', source: 'template', text: 'Key findings by month: ...', problems: ['A number is not in the findings: 25%.'] })

    expect(describeNarration(rejected, 'UTC')).toMatchObject({
      heading: 'Template summary: the AI summary did not pass the checks',
      problems: ['A number is not in the findings: 25%.'],
    })
  })

  it('says when the narrator did not answer', () => {
    const failed = record({ status: 'failed', source: 'template', problems: ['Ollama did not answer within 120 seconds.'] })

    expect(describeNarration(failed, 'UTC').heading).toBe('Template summary: the narrator did not answer')
  })
})
