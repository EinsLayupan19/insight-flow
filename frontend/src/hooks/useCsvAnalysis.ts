import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/http'
import {
  calculateMetrics,
  profileCsv,
  validateCsv,
  type CsvMetricsResponse,
  type CsvProfileResponse,
  type CsvUploadResponse,
} from '../api/uploads'
import type { ColumnMapping } from '../lib/columnMapping'
import { EMPTY_SELECTION, selectCsvFile, type FileSelection } from '../lib/files'

/** One request's lifecycle. `previous` keeps the last good result visible while refreshing or after a failed refresh. */
export type RequestState<T> =
  | { status: 'idle' }
  | { status: 'loading'; previous: T | null }
  | { status: 'success'; data: T }
  | { status: 'error'; message: string; previous: T | null }

/** One run of the workflow on one file. Results live only in this page's memory. */
export type Analysis = {
  id: number
  file: File
  validation: RequestState<CsvUploadResponse>
  profile: RequestState<CsvProfileResponse>
  metrics: RequestState<CsvMetricsResponse>
  /** Mapping sent with the latest metrics request (used by "Try again"). */
  requestedMapping: ColumnMapping
  /** Mapping behind the metrics currently shown. */
  appliedMapping: ColumnMapping
}

export function latestData<T>(state: RequestState<T>): T | null {
  if (state.status === 'success') return state.data
  if (state.status === 'loading' || state.status === 'error') return state.previous
  return null
}

function errorMessage(error: unknown): string {
  // ApiError messages are written for users. Anything else is a bug worth seeing in the console.
  if (error instanceof ApiError) return error.message
  console.error('Unexpected error during analysis:', error)
  return 'Something went wrong in the app. Try again, and check the browser console if it keeps happening.'
}

export function useCsvAnalysis() {
  const [selection, setSelection] = useState<FileSelection>(EMPTY_SELECTION)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  // One controller for validate + profile, and one for metrics, which can re-run on its own.
  const runController = useRef<AbortController | null>(null)
  const metricsController = useRef<AbortController | null>(null)
  const nextId = useRef(1)

  const abortAll = useCallback(() => {
    runController.current?.abort()
    metricsController.current?.abort()
  }, [])

  useEffect(() => abortAll, [abortAll]) // cancel in-flight requests if the page unmounts

  /** Apply `change` only while `id` is still the current analysis, so late responses are ignored. */
  const update = useCallback((id: number, change: (current: Analysis) => Analysis) => {
    setAnalysis((current) => (current?.id === id ? change(current) : current))
  }, [])

  const runProfile = useCallback(
    async (id: number, file: File, signal: AbortSignal) => {
      update(id, (a) => ({ ...a, profile: { status: 'loading', previous: latestData(a.profile) } }))
      try {
        const data = await profileCsv(file, signal)
        update(id, (a) => ({ ...a, profile: { status: 'success', data } }))
      } catch (error) {
        if (signal.aborted) return
        const message = errorMessage(error)
        update(id, (a) => ({ ...a, profile: { status: 'error', message, previous: latestData(a.profile) } }))
      }
    },
    [update],
  )

  const runMetrics = useCallback(
    async (id: number, file: File, mapping: ColumnMapping) => {
      metricsController.current?.abort() // a newer request replaces one still running
      const controller = new AbortController()
      metricsController.current = controller
      update(id, (a) => ({
        ...a,
        requestedMapping: mapping,
        metrics: { status: 'loading', previous: latestData(a.metrics) },
      }))
      try {
        const data = await calculateMetrics(file, mapping, controller.signal)
        update(id, (a) => ({ ...a, appliedMapping: mapping, metrics: { status: 'success', data } }))
      } catch (error) {
        if (controller.signal.aborted) return
        const message = errorMessage(error)
        update(id, (a) => ({ ...a, metrics: { status: 'error', message, previous: latestData(a.metrics) } }))
      }
    },
    [update],
  )

  const analyze = useCallback(
    async (file: File) => {
      abortAll()
      const controller = new AbortController()
      runController.current = controller
      const id = nextId.current++
      setAnalysis({
        id,
        file,
        validation: { status: 'loading', previous: null },
        profile: { status: 'idle' },
        metrics: { status: 'idle' },
        requestedMapping: {},
        appliedMapping: {},
      })

      try {
        const data = await validateCsv(file, controller.signal)
        update(id, (a) => ({ ...a, validation: { status: 'success', data } }))
      } catch (error) {
        if (controller.signal.aborted) return
        const message = errorMessage(error)
        update(id, (a) => ({ ...a, validation: { status: 'error', message, previous: null } }))
        return
      }

      // Both steps upload the same file again. They run in parallel and can fail independently.
      void runProfile(id, file, controller.signal)
      void runMetrics(id, file, {})
    },
    [abortAll, update, runProfile, runMetrics],
  )

  const selectFiles = useCallback((files: readonly File[]) => setSelection(selectCsvFile(files)), [])
  const clearSelection = useCallback(() => setSelection(EMPTY_SELECTION), [])

  const retryAnalysis = useCallback(() => {
    if (analysis) void analyze(analysis.file)
  }, [analysis, analyze])

  const retryProfile = useCallback(() => {
    const signal = runController.current?.signal
    if (analysis && signal && !signal.aborted) void runProfile(analysis.id, analysis.file, signal)
  }, [analysis, runProfile])

  const retryMetrics = useCallback(() => {
    if (analysis) void runMetrics(analysis.id, analysis.file, analysis.requestedMapping)
  }, [analysis, runMetrics])

  const applyMapping = useCallback(
    (mapping: ColumnMapping) => {
      if (analysis) void runMetrics(analysis.id, analysis.file, mapping)
    },
    [analysis, runMetrics],
  )

  /** Cancel anything running and forget the results. Used by "Cancel" and "Clear results". */
  const clearResults = useCallback(() => {
    abortAll()
    setAnalysis(null)
  }, [abortAll])

  return {
    selection,
    selectFiles,
    clearSelection,
    analysis,
    analyze,
    retryAnalysis,
    retryProfile,
    retryMetrics,
    applyMapping,
    clearResults,
  }
}

export type CsvAnalysisController = ReturnType<typeof useCsvAnalysis>
