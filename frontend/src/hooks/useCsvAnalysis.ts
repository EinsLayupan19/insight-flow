import { useCallback, useEffect, useRef, useState } from 'react'
import {
  runMetricsAnalysis,
  runPerformanceAnalysis,
  runProfileAnalysis,
  runTrendsAnalysis,
  saveDataset,
  type SaveDatasetResponse,
} from '../api/datasets'
import {
  calculateMetrics,
  calculatePerformance,
  calculateTrends,
  profileCsv,
  validateCsv,
  type ProductPerformance,
  type QualityReport,
  type RetailMetrics,
  type SalesTrends,
} from '../api/uploads'
import type { ColumnMapping } from '../lib/columnMapping'
import { DEFAULT_PERFORMANCE_OPTIONS, type PerformanceOptions } from '../lib/performance'
import { DEFAULT_TREND_OPTIONS, type TrendOptions } from '../lib/trends'
import { userMessage } from '../lib/errors'
import { EMPTY_SELECTION, selectCsvFile, type FileSelection } from '../lib/files'
import { failedFrom, loadingFrom, type RequestState } from '../lib/requestState'

/** What validation reports about a file. The upload and dataset endpoints both return these fields. */
export type FileSummary = {
  filename: string
  size_bytes: number
  row_count: number
  column_count: number
  columns: string[]
}

/** 'memory': analyzed and discarded. 'library': saved, with every analysis recorded in its history. */
export type StorageMode = 'memory' | 'library'

/** One run of the workflow on one file. The results shown here live in this page's memory. */
export type Analysis = {
  id: number
  file: File
  mode: StorageMode
  validation: RequestState<FileSummary>
  /** In library mode: the saved dataset (or the existing one with the same content). */
  saved: SaveDatasetResponse | null
  profile: RequestState<QualityReport>
  metrics: RequestState<RetailMetrics>
  /** Mapping sent with the latest metrics request (used by "Try again"). */
  requestedMapping: ColumnMapping
  /** Mapping behind the metrics currently shown. */
  appliedMapping: ColumnMapping
  trends: RequestState<SalesTrends>
  /** Inputs of the latest trends request (used by "Try again" and when only one option changes). */
  trendsRequest: TrendsRequest
  /** Grain and date column behind the trends currently shown. */
  appliedTrendOptions: TrendOptions
  performance: RequestState<ProductPerformance>
  /** Inputs of the latest performance request (used by "Try again" and when a label column changes). */
  performanceRequest: PerformanceRequest
}

/** Trends share the metrics' column choices and add a grain and a date column. */
type TrendsRequest = { mapping: ColumnMapping; options: TrendOptions }

/** Product and category performance shares the metrics' column choices and adds the label columns. */
type PerformanceRequest = { mapping: ColumnMapping; options: PerformanceOptions }

/** Where results come from: the saved dataset (recorded in its history), or the file itself (not stored). */
type Source = { file: File; datasetId: number | null }

const sourceOf = (analysis: Analysis): Source => ({ file: analysis.file, datasetId: analysis.saved?.dataset.id ?? null })

async function validateOrSave(
  file: File,
  mode: StorageMode,
  signal: AbortSignal,
): Promise<{ summary: FileSummary; saved: SaveDatasetResponse | null }> {
  if (mode === 'memory') return { summary: await validateCsv(file, signal), saved: null }
  const saved = await saveDataset(file, signal)
  return { summary: saved.dataset, saved }
}

async function fetchProfile(source: Source, signal: AbortSignal): Promise<QualityReport> {
  if (source.datasetId !== null) return (await runProfileAnalysis(source.datasetId, signal)).result
  return (await profileCsv(source.file, signal)).profile
}

async function fetchMetrics(source: Source, mapping: ColumnMapping, signal: AbortSignal): Promise<RetailMetrics> {
  if (source.datasetId !== null) return (await runMetricsAnalysis(source.datasetId, mapping, signal)).result
  return (await calculateMetrics(source.file, mapping, signal)).metrics
}

async function fetchTrends(source: Source, request: TrendsRequest, signal: AbortSignal): Promise<SalesTrends> {
  if (source.datasetId !== null) return (await runTrendsAnalysis(source.datasetId, request.mapping, request.options, signal)).result
  return (await calculateTrends(source.file, request.mapping, request.options, signal)).trends
}

async function fetchPerformance(source: Source, request: PerformanceRequest, signal: AbortSignal): Promise<ProductPerformance> {
  if (source.datasetId !== null) {
    return (await runPerformanceAnalysis(source.datasetId, request.mapping, request.options, signal)).result
  }
  return (await calculatePerformance(source.file, request.mapping, request.options, signal)).performance
}

export function useCsvAnalysis() {
  const [selection, setSelection] = useState<FileSelection>(EMPTY_SELECTION)
  const [saveToLibrary, setSaveToLibrary] = useState(true)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  // One controller for validate + profile, and one each for metrics, trends, and performance, which can re-run on their own.
  const runController = useRef<AbortController | null>(null)
  const metricsController = useRef<AbortController | null>(null)
  const trendsController = useRef<AbortController | null>(null)
  const performanceController = useRef<AbortController | null>(null)
  const nextId = useRef(1)

  const abortAll = useCallback(() => {
    runController.current?.abort()
    metricsController.current?.abort()
    trendsController.current?.abort()
    performanceController.current?.abort()
  }, [])

  useEffect(() => abortAll, [abortAll]) // cancel in-flight requests if the app unmounts

  /** Apply `change` only while `id` is still the current analysis, so late responses are ignored. */
  const update = useCallback((id: number, change: (current: Analysis) => Analysis) => {
    setAnalysis((current) => (current?.id === id ? change(current) : current))
  }, [])

  const runProfile = useCallback(
    async (id: number, source: Source, signal: AbortSignal) => {
      update(id, (a) => ({ ...a, profile: loadingFrom(a.profile) }))
      try {
        const data = await fetchProfile(source, signal)
        update(id, (a) => ({ ...a, profile: { status: 'success', data } }))
      } catch (error) {
        if (signal.aborted) return
        const message = userMessage(error)
        update(id, (a) => ({ ...a, profile: failedFrom(a.profile, message) }))
      }
    },
    [update],
  )

  const runMetrics = useCallback(
    async (id: number, source: Source, mapping: ColumnMapping) => {
      metricsController.current?.abort() // a newer request replaces one still running
      const controller = new AbortController()
      metricsController.current = controller
      update(id, (a) => ({ ...a, requestedMapping: mapping, metrics: loadingFrom(a.metrics) }))
      try {
        const data = await fetchMetrics(source, mapping, controller.signal)
        update(id, (a) => ({ ...a, appliedMapping: mapping, metrics: { status: 'success', data } }))
      } catch (error) {
        if (controller.signal.aborted) return
        const message = userMessage(error)
        update(id, (a) => ({ ...a, metrics: failedFrom(a.metrics, message) }))
      }
    },
    [update],
  )

  const runTrends = useCallback(
    async (id: number, source: Source, request: TrendsRequest) => {
      trendsController.current?.abort() // a newer request replaces one still running
      const controller = new AbortController()
      trendsController.current = controller
      update(id, (a) => ({ ...a, trendsRequest: request, trends: loadingFrom(a.trends) }))
      try {
        const data = await fetchTrends(source, request, controller.signal)
        update(id, (a) => ({ ...a, appliedTrendOptions: request.options, trends: { status: 'success', data } }))
      } catch (error) {
        if (controller.signal.aborted) return
        const message = userMessage(error)
        update(id, (a) => ({ ...a, trends: failedFrom(a.trends, message) }))
      }
    },
    [update],
  )

  const runPerformance = useCallback(
    async (id: number, source: Source, request: PerformanceRequest) => {
      performanceController.current?.abort() // a newer request replaces one still running
      const controller = new AbortController()
      performanceController.current = controller
      update(id, (a) => ({ ...a, performanceRequest: request, performance: loadingFrom(a.performance) }))
      try {
        const data = await fetchPerformance(source, request, controller.signal)
        update(id, (a) => ({ ...a, performance: { status: 'success', data } }))
      } catch (error) {
        if (controller.signal.aborted) return
        const message = userMessage(error)
        update(id, (a) => ({ ...a, performance: failedFrom(a.performance, message) }))
      }
    },
    [update],
  )

  const analyze = useCallback(
    async (file: File, mode: StorageMode) => {
      abortAll()
      const controller = new AbortController()
      runController.current = controller
      const id = nextId.current++
      setAnalysis({
        id,
        file,
        mode,
        validation: { status: 'loading', previous: null },
        saved: null,
        profile: { status: 'idle' },
        metrics: { status: 'idle' },
        requestedMapping: {},
        appliedMapping: {},
        trends: { status: 'idle' },
        trendsRequest: { mapping: {}, options: DEFAULT_TREND_OPTIONS },
        appliedTrendOptions: DEFAULT_TREND_OPTIONS,
        performance: { status: 'idle' },
        performanceRequest: { mapping: {}, options: DEFAULT_PERFORMANCE_OPTIONS },
      })

      let source: Source
      try {
        const { summary, saved } = await validateOrSave(file, mode, controller.signal)
        update(id, (a) => ({ ...a, saved, validation: { status: 'success', data: summary } }))
        source = { file, datasetId: saved?.dataset.id ?? null }
      } catch (error) {
        if (controller.signal.aborted) return
        const message = userMessage(error)
        update(id, (a) => ({ ...a, validation: { status: 'error', message, previous: null } }))
        return
      }

      // The steps run in parallel and can fail independently.
      void runProfile(id, source, controller.signal)
      void runMetrics(id, source, {})
      void runTrends(id, source, { mapping: {}, options: DEFAULT_TREND_OPTIONS })
      void runPerformance(id, source, { mapping: {}, options: DEFAULT_PERFORMANCE_OPTIONS })
    },
    [abortAll, update, runProfile, runMetrics, runTrends, runPerformance],
  )

  const selectFiles = useCallback((files: readonly File[]) => setSelection(selectCsvFile(files)), [])
  const clearSelection = useCallback(() => setSelection(EMPTY_SELECTION), [])

  const analyzeSelected = useCallback(
    (file: File) => void analyze(file, saveToLibrary ? 'library' : 'memory'),
    [analyze, saveToLibrary],
  )

  /** Repeat the same run (same file, same storage choice). */
  const retryAnalysis = useCallback(() => {
    if (analysis) void analyze(analysis.file, analysis.mode)
  }, [analysis, analyze])

  const retryProfile = useCallback(() => {
    const signal = runController.current?.signal
    if (analysis && signal && !signal.aborted) void runProfile(analysis.id, sourceOf(analysis), signal)
  }, [analysis, runProfile])

  const retryMetrics = useCallback(() => {
    if (analysis) void runMetrics(analysis.id, sourceOf(analysis), analysis.requestedMapping)
  }, [analysis, runMetrics])

  const retryTrends = useCallback(() => {
    if (analysis) void runTrends(analysis.id, sourceOf(analysis), analysis.trendsRequest)
  }, [analysis, runTrends])

  const retryPerformance = useCallback(() => {
    if (analysis) void runPerformance(analysis.id, sourceOf(analysis), analysis.performanceRequest)
  }, [analysis, runPerformance])

  /** New column choices apply to the metrics, the trends, and the product and category rankings. */
  const applyMapping = useCallback(
    (mapping: ColumnMapping) => {
      if (!analysis) return
      void runMetrics(analysis.id, sourceOf(analysis), mapping)
      void runTrends(analysis.id, sourceOf(analysis), { mapping, options: analysis.trendsRequest.options })
      void runPerformance(analysis.id, sourceOf(analysis), { mapping, options: analysis.performanceRequest.options })
    },
    [analysis, runMetrics, runTrends, runPerformance],
  )

  /** A different product or category column re-runs the rankings only. */
  const changePerformanceOptions = useCallback(
    (options: PerformanceOptions) => {
      if (analysis) void runPerformance(analysis.id, sourceOf(analysis), { mapping: analysis.performanceRequest.mapping, options })
    },
    [analysis, runPerformance],
  )

  /** A different grain or date column re-runs the trends only. */
  const changeTrendOptions = useCallback(
    (options: TrendOptions) => {
      if (analysis) void runTrends(analysis.id, sourceOf(analysis), { mapping: analysis.trendsRequest.mapping, options })
    },
    [analysis, runTrends],
  )

  /** Cancel anything running and forget the results shown. Saved datasets are not affected. */
  const clearResults = useCallback(() => {
    abortAll()
    setAnalysis(null)
  }, [abortAll])

  return {
    selection,
    selectFiles,
    clearSelection,
    saveToLibrary,
    setSaveToLibrary,
    analysis,
    analyze: analyzeSelected,
    retryAnalysis,
    retryProfile,
    retryMetrics,
    retryTrends,
    retryPerformance,
    applyMapping,
    changeTrendOptions,
    changePerformanceOptions,
    clearResults,
  }
}

export type CsvAnalysisController = ReturnType<typeof useCsvAnalysis>
