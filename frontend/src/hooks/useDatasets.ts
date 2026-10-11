import { useCallback, useEffect, useState } from 'react'
import {
  deleteDataset,
  getAnalysis,
  getDataset,
  listAnalyses,
  listDatasets,
  runMetricsAnalysis,
  runProfileAnalysis,
  type AnalysisRecord,
  type AnalysisSummary,
  type DatasetDetail,
  type DatasetSummary,
} from '../api/datasets'
import type { ColumnMapping } from '../lib/columnMapping'
import { selectedAnalysisId } from '../lib/datasetDisplay'
import { userMessage } from '../lib/errors'
import { failedFrom, latestData, loadingFrom, type RequestState } from '../lib/requestState'

const LOADING = { status: 'loading', previous: null } as const

/** The saved datasets, loaded when the page opens. */
export function useDatasetList() {
  const [state, setState] = useState<RequestState<DatasetSummary[]>>(LOADING)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    listDatasets(controller.signal).then(
      (data) => setState({ status: 'success', data }),
      (error: unknown) => {
        if (!controller.signal.aborted) setState((current) => failedFrom(current, userMessage(error)))
      },
    )
    return () => controller.abort()
  }, [attempt])

  const reload = useCallback(() => {
    setState(loadingFrom)
    setAttempt((n) => n + 1)
  }, [])

  return { state, reload }
}

export type DatasetAction = 'profile' | 'metrics' | 'delete'

/**
 * One saved dataset: its details, its analysis history, the analysis being viewed, and the
 * actions on it. Mount it with key={datasetId} so a different dataset starts fresh.
 */
export function useDatasetDetail(datasetId: number, requestedAnalysisId: number | null) {
  const [dataset, setDataset] = useState<RequestState<DatasetDetail>>(LOADING)
  const [analyses, setAnalyses] = useState<RequestState<AnalysisSummary[]>>(LOADING)
  const [reloadKey, setReloadKey] = useState(0)
  const [records, setRecords] = useState<Record<number, AnalysisRecord>>({}) // full results, by analysis id
  const [recordError, setRecordError] = useState<{ id: number; message: string } | null>(null)
  const [running, setRunning] = useState<DatasetAction | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  // Details and history, loaded together (and again after every new analysis).
  useEffect(() => {
    const controller = new AbortController()
    const fail = (error: unknown) => (controller.signal.aborted ? null : userMessage(error))
    getDataset(datasetId, controller.signal).then(
      (data) => setDataset({ status: 'success', data }),
      (error: unknown) => {
        const message = fail(error)
        if (message) setDataset((current) => failedFrom(current, message))
      },
    )
    listAnalyses(datasetId, controller.signal).then(
      (data) => setAnalyses({ status: 'success', data }),
      (error: unknown) => {
        const message = fail(error)
        if (message) setAnalyses((current) => failedFrom(current, message))
      },
    )
    return () => controller.abort()
  }, [datasetId, reloadKey])

  const selectedId = selectedAnalysisId(latestData(analyses), requestedAnalysisId)
  const cached = selectedId === null ? undefined : records[selectedId]

  // The full result of the analysis being viewed, unless it is already cached. A reload retries it.
  useEffect(() => {
    if (selectedId === null || cached) return
    const controller = new AbortController()
    getAnalysis(datasetId, selectedId, controller.signal).then(
      (record) => setRecords((current) => ({ ...current, [record.id]: record })),
      (error: unknown) => {
        if (!controller.signal.aborted) setRecordError({ id: selectedId, message: userMessage(error) })
      },
    )
    return () => controller.abort()
  }, [datasetId, selectedId, cached, reloadKey])

  let record: RequestState<AnalysisRecord> = { status: 'idle' }
  if (cached) record = { status: 'success', data: cached }
  else if (selectedId !== null && recordError?.id === selectedId) record = { status: 'error', message: recordError.message, previous: null }
  else if (selectedId !== null) record = LOADING

  const reload = useCallback(() => {
    setDataset(loadingFrom)
    setAnalyses(loadingFrom)
    setRecordError(null)
    setReloadKey((n) => n + 1)
  }, [])

  /** Run an analysis on the stored file. Resolves to the new record, or null if it failed (see actionError). */
  const runAnalysis = useCallback(
    async (kind: 'profile' | 'metrics', mapping: ColumnMapping = {}): Promise<AnalysisRecord | null> => {
      setRunning(kind)
      setActionError(null)
      try {
        const created = kind === 'profile' ? await runProfileAnalysis(datasetId) : await runMetricsAnalysis(datasetId, mapping)
        setRecords((current) => ({ ...current, [created.id]: created }))
        setReloadKey((n) => n + 1) // refresh the history and counts; the current view stays meanwhile
        return created
      } catch (error) {
        setActionError(userMessage(error))
        return null
      } finally {
        setRunning(null)
      }
    },
    [datasetId],
  )

  /** Delete the dataset. Resolves to true on success; on failure the reason is in actionError. */
  const remove = useCallback(async (): Promise<boolean> => {
    setRunning('delete')
    setActionError(null)
    try {
      await deleteDataset(datasetId)
      return true
    } catch (error) {
      setActionError(userMessage(error))
      return false
    } finally {
      setRunning(null)
    }
  }, [datasetId])

  return { dataset, analyses, selectedId, record, reload, runAnalysis, remove, running, actionError }
}
