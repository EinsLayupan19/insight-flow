// One trend (revenue, orders, or average order value) per period, drawn as columns, or as a
// line when periods are too dense for columns. Periods without a value are left empty, never
// drawn as zero. Hover or arrow keys show each period's value; the table below the chart
// shows every value without needing either.

import { useState, type KeyboardEvent, type PointerEvent } from 'react'
import type { SalesTrends } from '../api/uploads'
import { useElementWidth } from '../hooks/useElementWidth'
import { formatCount, formatMetricValue } from '../lib/format'
import {
  axisLabel,
  chartMode,
  columnLayout,
  columnPath,
  describeTrendSeries,
  formatPeriod,
  niceTicks,
  pickTickIndexes,
  seriesValues,
  spansYears,
  summarizeTrend,
  type TrendKey,
} from '../lib/trends'

const HEIGHT = 260
const MARGIN = { top: 12, right: 8, bottom: 30 }
const MIN_LABEL_SPACING = 88 // px per x-axis label
const AXIS_COMPACT = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 })

type TrendChartProps = { trends: SalesTrends; seriesKey: TrendKey }

export function TrendChart({ trends, seriesKey }: TrendChartProps) {
  const [containerRef, width] = useElementWidth<HTMLDivElement>()
  const [active, setActive] = useState<number | null>(null)

  const { periods } = trends
  const series = trends[seriesKey]
  const presentation = describeTrendSeries(seriesKey, trends)
  const values = seriesValues(series, periods.length)
  const present = values.filter((value): value is number => value !== null)
  const ticks = niceTicks(Math.min(0, ...present), Math.max(0, ...present))
  const tickLabels = ticks.map((tick) => AXIS_COMPACT.format(tick))

  // The value axis takes as much room as its longest label.
  const left = Math.max(...tickLabels.map((label) => label.length)) * 7 + 14
  const plotWidth = Math.max(0, width - left - MARGIN.right)
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom
  const [low, high] = [ticks[0], ticks[ticks.length - 1]]
  const y = (value: number) => MARGIN.top + ((high - value) / (high - low)) * plotHeight
  const { band, barWidth } = columnLayout(periods.length, plotWidth)
  const centerX = (index: number) => left + band * (index + 0.5)
  const mode = chartMode(periods.length, plotWidth)
  const multiYear = spansYears(periods)
  const labelIndexes = pickTickIndexes(periods.length, Math.max(2, Math.floor(plotWidth / MIN_LABEL_SPACING)))

  const indexAt = (clientX: number, element: Element) => {
    const x = clientX - element.getBoundingClientRect().left - left
    return Math.min(periods.length - 1, Math.max(0, Math.floor(x / band)))
  }
  const onPointerMove = (event: PointerEvent<SVGRectElement>) => setActive(indexAt(event.clientX, event.currentTarget.ownerSVGElement ?? event.currentTarget))

  // One tab stop for the whole chart; arrow keys move between periods (no motion: keyboard actions are instant).
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const last = periods.length - 1
    const next: Record<string, number> = {
      ArrowRight: active === null ? 0 : Math.min(last, active + 1),
      ArrowLeft: active === null ? last : Math.max(0, active - 1),
      Home: 0,
      End: last,
    }
    if (event.key in next) {
      event.preventDefault()
      setActive(next[event.key])
    } else if (event.key === 'Escape') {
      setActive(null)
    }
  }

  const readout = active === null ? null : describePoint(active)
  function describePoint(index: number) {
    const period = periods[index]
    const value = values[index]
    const label = formatPeriod(period, trends.grain)
    if (value !== null) {
      const rows = series.points[index]?.rows_included ?? 0
      return { label, value: formatMetricValue(value, presentation.format).text, detail: `Based on ${formatCount(rows)} ${rows === 1 ? 'row' : 'rows'}` }
    }
    if (period.row_count === 0) return { label, value: 'No rows', detail: 'No row has a date in this period' }
    return { label, value: 'Not available', detail: 'Rows exist, but none had a usable value' }
  }

  const linePath = mode === 'line' ? lineSegments(values, centerX, y) : ''
  const isolated = mode === 'line' ? values.flatMap((value, index) => (value !== null && values[index - 1] == null && values[index + 1] == null ? [index] : [])) : []

  return (
    <div
      ref={containerRef}
      className="trend-chart"
      tabIndex={0}
      role="group"
      aria-label={summarizeTrend(trends, seriesKey)}
      aria-describedby="trend-chart-help"
      onKeyDown={onKeyDown}
      onBlur={() => setActive(null)}
    >
      <p id="trend-chart-help" className="sr-only">
        Use the left and right arrow keys to read each period. The table below lists every value.
      </p>
      {width > 0 && (
        <svg width={width} height={HEIGHT} aria-hidden="true" focusable="false">
          {ticks.map((tick, index) => (
            <g key={tick}>
              <line className={tick === 0 ? 'trend-baseline' : 'trend-grid'} x1={left} x2={left + plotWidth} y1={y(tick)} y2={y(tick)} />
              <text className="trend-axis-label" x={left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                {tickLabels[index]}
              </text>
            </g>
          ))}

          {active !== null && <rect className="trend-active-band" x={left + band * active} y={MARGIN.top} width={band} height={plotHeight} />}

          {mode === 'columns' &&
            values.map((value, index) =>
              value === null || value === 0 ? null : (
                <path key={periods[index].start} className="trend-column" d={columnPath(centerX(index), y(0), y(value), barWidth, 4)} />
              ),
            )}

          {mode === 'line' && (
            <>
              <path className="trend-line" d={linePath} />
              {isolated.map((index) => (
                <circle key={periods[index].start} className="trend-dot" cx={centerX(index)} cy={y(values[index] as number)} r={4} />
              ))}
              {active !== null && <line className="trend-crosshair" x1={centerX(active)} x2={centerX(active)} y1={MARGIN.top} y2={MARGIN.top + plotHeight} />}
              {active !== null && values[active] !== null && (
                <circle className="trend-dot" cx={centerX(active)} cy={y(values[active] as number)} r={4} />
              )}
            </>
          )}

          {labelIndexes.map((index) => {
            const anchor = band >= MIN_LABEL_SPACING ? 'middle' : index === 0 ? 'start' : index === periods.length - 1 ? 'end' : 'middle'
            const x = anchor === 'start' ? left : anchor === 'end' ? left + plotWidth : centerX(index)
            return (
              <text key={periods[index].start} className="trend-axis-label" x={x} y={HEIGHT - 8} textAnchor={anchor}>
                {axisLabel(periods[index], trends.grain, multiYear)}
              </text>
            )
          })}

          {/* The hit target is the whole plot: the nearest period answers, not only its painted column. */}
          <rect
            className="trend-hit-area"
            x={left}
            y={MARGIN.top}
            width={plotWidth}
            height={plotHeight}
            onPointerMove={onPointerMove}
            onPointerLeave={() => setActive(null)}
          />
        </svg>
      )}

      {readout && active !== null && (
        <div
          className="trend-tooltip"
          style={{ left: Math.min(Math.max(centerX(active), 90), Math.max(width - 90, 90)) }}
        >
          <p className="trend-tooltip-value">{readout.value}</p>
          <p className="trend-tooltip-label">{readout.label}</p>
          <p className="trend-tooltip-detail">{readout.detail}</p>
        </div>
      )}
      <p className="sr-only" aria-live="polite">
        {readout ? `${readout.label}: ${readout.value}. ${readout.detail}.` : ''}
      </p>
    </div>
  )
}

/** An SVG path through consecutive values, broken wherever a period has no value. */
function lineSegments(values: (number | null)[], x: (index: number) => number, y: (value: number) => number): string {
  let path = ''
  values.forEach((value, index) => {
    if (value === null) return
    path += `${values[index - 1] == null ? 'M' : 'L'}${x(index)},${y(value)} `
  })
  return path.trim()
}
