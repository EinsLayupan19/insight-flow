// The top products or categories as horizontal bars: long labels stay readable, every bar grows
// from the same zero line (negative revenue grows left), and each value is printed at its bar's
// end, so nothing depends on hovering. The table below lists every group.

import type { PerformanceGroup } from '../api/uploads'
import { useElementWidth } from '../hooks/useElementWidth'
import { formatMetricValue, type ValueFormat } from '../lib/format'
import { barScale, type RankKey } from '../lib/performance'

const ROW_HEIGHT = 30
const BAR_HEIGHT = 16
const AXIS_HEIGHT = 24
const VALUE_SPACE = 84 // room for the value printed at a bar's end
const CHAR_WIDTH = 7 // approximate width of one label character at 12px
const AXIS_COMPACT = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 })

type PerformanceChartProps = {
  groups: PerformanceGroup[] // already ranked, at most the top 10
  rankKey: RankKey
  format: ValueFormat
  summary: string
}

export function PerformanceChart({ groups, rankKey, format, summary }: PerformanceChartProps) {
  const [containerRef, width] = useElementWidth<HTMLDivElement>()
  const values = groups.map((group) => group[rankKey])
  const { min, max, ticks } = barScale(values.filter((value): value is number => value !== null))

  const labelWidth = Math.min(180, Math.max(90, Math.round(width * 0.32)))
  const hasNegative = min < 0
  const plotLeft = labelWidth + 12 + (hasNegative ? VALUE_SPACE : 0)
  const plotWidth = Math.max(0, width - plotLeft - VALUE_SPACE)
  const x = (value: number) => plotLeft + ((value - min) / (max - min)) * plotWidth
  const height = groups.length * ROW_HEIGHT + AXIS_HEIGHT
  const maxChars = Math.floor(labelWidth / CHAR_WIDTH)

  return (
    <div ref={containerRef} className="performance-chart">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={summary}>
          {ticks.map((tick) => (
            <g key={tick}>
              <line className={tick === 0 ? 'trend-baseline' : 'trend-grid'} x1={x(tick)} x2={x(tick)} y1={0} y2={height - AXIS_HEIGHT} />
              <text className="trend-axis-label" x={x(tick)} y={height - 6} textAnchor="middle">
                {AXIS_COMPACT.format(tick)}
              </text>
            </g>
          ))}

          {groups.map((group, index) => {
            const value = values[index]
            const center = index * ROW_HEIGHT + ROW_HEIGHT / 2
            const label = group.label.length > maxChars ? `${group.label.slice(0, Math.max(1, maxChars - 1))}…` : group.label
            return (
              <g key={group.label}>
                <text className="performance-bar-label" x={labelWidth} y={center} dy="0.32em" textAnchor="end">
                  <title>{group.label}</title>
                  {label}
                </text>
                {value === null ? (
                  <text className="performance-bar-value is-missing" x={x(0) + 6} y={center} dy="0.32em">
                    No value
                  </text>
                ) : (
                  <>
                    {value !== 0 && <path className="trend-column" d={barPath(x(0), x(value), center, BAR_HEIGHT, 4)} />}
                    <text
                      className="performance-bar-value"
                      x={value < 0 ? x(value) - 6 : x(value) + 6}
                      y={center}
                      dy="0.32em"
                      textAnchor={value < 0 ? 'end' : 'start'}
                    >
                      {formatMetricValue(value, format).text}
                    </text>
                  </>
                )}
              </g>
            )
          })}
        </svg>
      )}
    </div>
  )
}

/** A horizontal bar from the zero line x0 to x1. Only the data end is rounded. */
function barPath(x0: number, x1: number, center: number, height: number, radius: number): string {
  const r = Math.min(radius, height / 2, Math.abs(x1 - x0))
  const top = center - height / 2
  const bottom = center + height / 2
  const right = x1 >= x0 // positive values grow to the right
  const edge = right ? x1 - r : x1 + r
  return `M${x0},${top} H${edge} Q${x1},${top} ${x1},${top + r} V${bottom - r} Q${x1},${bottom} ${edge},${bottom} H${x0} Z`
}
