import { useCallback, useEffect, useRef, useState } from 'react'
import {
  runInsightsAnalysis,
  runMetricsAnalysis,
  runPerformanceAnalysis,
  runProfileAnalysis,
  runTrendsAnalysis,
  saveDataset,
  type SaveDatasetResponse,
} from '../api/datasets'
import {
  calculateInsights,
  calculateMetrics,
  calculatePerformance,
  calculateTrends,
  profileCsv,
  validateCsv,
  type ProductPerformance,
  type QualityReport,
  type RetailMetrics,
  type SalesInsights,
  type SalesTrends,
} from '../api/uploads'
import type { ColumnMapping } from '../lib/columnMapping'
import { DEFAULT_INSIGHT_OPTIONS, insightOptionsFrom, type InsightOptions } from '../lib/insights'
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
  insights: RequestState<SalesInsights>
  /** Inputs of the latest insights request (used by "Try again"). */
  insightsRequest: InsightsRequest
}

/** Trends share the metrics' column choices and add a grain and a date column. */
type TrendsRequest = { mapping: ColumnMapping; options: TrendOptions }

/** Product and category performance shares the metrics' column choices and adds the label columns. */
type PerformanceRequest = { mapping: ColumnMapping; options: PerformanceOptions }

/** Insights follow the other sections: the column mapping, the trends' grain and date, and the label columns. */
type InsightsRequest = { mapping: ColumnMapping; options: InsightOptions }

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

async function fetchInsights(source: Source, request: InsightsRequest, signal: AbortSignal): Promise<SalesInsights> {
  if (source.datasetId !== null) {
    return (await runInsightsAnalysis(source.datasetId, request.mapping, request.options, signal)).result
  }
  return (await calculateInsights(source.file, request.mapping, request.options, signal)).insights
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
  const insightsController = useRef<AbortController | null>(null)
  const nextId = useRef(1)

  const abortAll = useCallback(() => {
    runController.current?.abort()
    metricsController.current?.abort()
    trendsController.current?.abort()
    performanceController.current?.abort()
    insightsController.current?.abort()
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

  const runInsights = useCallback(
    async (id: number, source: Source, request: InsightsRequest) => {
      insightsController.current?.abort() // a newer request replaces one still running
      const controller = new AbortController()
      insightsController.current = controller
      update(id, (a) => ({ ...a, insightsRequest: request, insights: loadingFrom(a.insights) }))
      try {
        const data = await fetchInsights(source, request, controller.signal)
        update(id, (a) => ({ ...a, insights: { status: 'success', data } }))
      } catch (error) {
        if (controller.signal.aborted) return
        const message = userMessage(error)
        update(id, (a) => ({ ...a, insights: failedFrom(a.insights, message) }))
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
        insights: { status: 'idle' },
        insightsRequest: { mapping: {}, options: DEFAULT_INSIGHT_OPTIONS },
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
      void runInsights(id, source, { mapping: {}, options: DEFAULT_INSIGHT_OPTIONS })
    },
    [abortAll, update, runProfile, runMetrics, runTrends, runPerformance, runInsights],
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

  const retryInsights = useCallback(() => {
    if (analysis) void runInsights(analysis.id, sourceOf(analysis), analysis.insightsRequest)
  }, [analysis, runInsights])

  /** New column choices apply to every analysis that uses them, and to the findings. */
  const applyMapping = useCallback(
    (mapping: ColumnMapping) => {
      if (!analysis) return
      const source = sourceOf(analysis)
      void runMetrics(analysis.id, source, mapping)
      void runTrends(analysis.id, source, { mapping, options: analysis.trendsRequest.options })
      void runPerformance(analysis.id, source, { mapping, options: analysis.performanceRequest.options })
      const options = insightOptionsFrom(analysis.trendsRequest.options, analysis.performanceRequest.options)
      void runInsights(analysis.id, source, { mapping, options })
    },
    [analysis, runMetrics, runTrends, runPerformance, runInsights],
  )

  /** A different product or category column re-runs the rankings, and the findings that use them. */
  const changePerformanceOptions = useCallback(
    (options: PerformanceOptions) => {
      if (!analysis) return
      void runPerformance(analysis.id, sourceOf(analysis), { mapping: analysis.performanceRequest.mapping, options })
      const insightOptions = insightOptionsFrom(analysis.trendsRequest.options, options)
      void runInsights(analysis.id, sourceOf(analysis), { mapping: analysis.insightsRequest.mapping, options: insightOptions })
    },
    [analysis, runPerformance, runInsights],
  )

  /** A different grain or date column re-runs the trends, and the findings that use them. */
  const changeTrendOptions = useCallback(
    (options: TrendOptions) => {
      if (!analysis) return
      void runTrends(analysis.id, sourceOf(analysis), { mapping: analysis.trendsRequest.mapping, options })
      const insightOptions = insightOptionsFrom(options, analysis.performanceRequest.options)
      void runInsights(analysis.id, sourceOf(analysis), { mapping: analysis.insightsRequest.mapping, options: insightOptions })
    },
    [analysis, runTrends, runInsights],
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
    retryInsights,
    applyMapping,
    changeTrendOptions,
    changePerformanceOptions,
    clearResults,
  }
}

export type CsvAnalysisController = ReturnType<typeof useCsvAnalysis>
