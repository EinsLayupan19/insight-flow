// Sales trends from the API (calculated live, or recorded in a dataset's history): revenue,
// orders, and average order value per day, week, or month, as a chart and a table, with the
// API's own definitions, notes, and row counts. Nothing is recalculated here.

import { useState, type ReactNode } from 'react'
import type { Grain, MetricResult, SalesTrends, TrendSeries } from '../api/uploads'
import { formatCount, formatMetricValue, pluralize } from '../lib/format'
import { latestData, type RequestState } from '../lib/requestState'
import {
  GRAINS,
  GRAIN_LABELS,
  GRAIN_UNITS,
  TREND_KEYS,
  describeTrendSeries,
  trendTable,
  type TrendCell,
  type TrendKey,
  type TrendOptions,
} from '../lib/trends'
import { MeasureEvidence, Notes } from './Evidence'
import { Callout, LoadingState } from './Feedback'
import { Spinner } from './Icons'
import { TrendChart } from './TrendChart'

type TrendsSectionProps = {
  state: RequestState<SalesTrends>
  columns: string[]
  options: TrendOptions
  onChangeOptions: (options: TrendOptions) => void
  onRetry: () => void
}

/** The trends card on the analysis page. Column choices from Retail metrics apply here too. */
export function TrendsSection({ state, columns, options, onChangeOptions, onRetry }: TrendsSectionProps) {
  const data = latestData(state)
  const busy = state.status === 'loading'

  return (
    <section id="sales-trends" className="card section-card" aria-labelledby="trends-heading" aria-busy={busy}>
      <header className="section-header">
        <h3 id="trends-heading">Sales trends</h3>
        <p>Revenue, orders, and average order value per period, from rows with a usable date.</p>
      </header>

      {state.status === 'error' && (
        <Callout
          tone="critical"
          title={data ? 'The trends could not be updated' : 'The trends could not be calculated'}
          action={
            <button type="button" className="button-secondary" onClick={onRetry}>
              Try again
            </button>
          }
        >
          {state.message}
          {data && ' The trends below are from the last successful calculation.'}
        </Callout>
      )}

      {data !== null ? (
        <TrendsView trends={data} columns={columns} options={options} busy={busy} onChangeOptions={onChangeOptions}>
          <p className="small muted">
            Order ID, quantity, unit price, and revenue columns follow <strong>Map columns</strong> in Retail metrics.
          </p>
        </TrendsView>
      ) : (
        state.status !== 'error' && <LoadingState>Calculating sales trends…</LoadingState>
      )}
    </section>
  )
}

type TrendsViewProps = {
  trends: SalesTrends
  columns: string[]
  /** The options behind the trends shown. Changing one asks for a new calculation. */
  options: TrendOptions
  /** A new calculation is running: the trends shown are dimmed until it finishes. */
  busy: boolean
  /** The options can't be changed right now (for example, another action is running). */
  disabled?: boolean
  onChangeOptions: (options: TrendOptions) => void
  children?: ReactNode
}

export function TrendsView({ trends, columns, options, busy, disabled = false, onChangeOptions, children }: TrendsViewProps) {
  const [seriesKey, setSeriesKey] = useState<TrendKey>('revenue')
  const series = trends[seriesKey]
  const presentation = describeTrendSeries(seriesKey, trends)
  const hasPeriods = trends.periods.length > 0

  return (
    <>
      <TrendControls columns={columns} options={options} disabled={busy || disabled} onChange={onChangeOptions} />
      {children}
      {busy && (
        <p className="updating-note" role="status">
          <Spinner /> Recalculating trends…
        </p>
      )}

      {/* While recalculating, the previous trends stay visible but dimmed. */}
      <div className={busy ? 'trends-body is-stale' : 'trends-body'}>
        <DatedRows dated={trends.dated_rows} grain={trends.grain} periodCount={trends.periods.length} />

        {hasPeriods ? (
          <>
            <div className="segmented" role="radiogroup" aria-label="Trend to chart">
              {TREND_KEYS.map((key) => (
                <label key={key} className="segment">
                  <input
                    type="radio"
                    name="trend-series"
                    value={key}
                    checked={key === seriesKey}
                    onChange={() => setSeriesKey(key)}
                  />
                  <span>{describeTrendSeries(key, trends).label}</span>
                </label>
              ))}
            </div>

            <figure className="trend-figure">
              <figcaption className="trend-figure-title">
                {presentation.label} by {GRAIN_UNITS[trends.grain]}
              </figcaption>
              {series.status === 'calculated' ? (
                <>
                  <TrendChart key={`${seriesKey}-${trends.grain}`} trends={trends} seriesKey={seriesKey} />
                  <p className="small muted">Periods with no rows are left empty, not drawn as zero.</p>
                </>
              ) : (
                <SeriesUnavailable series={series} label={presentation.label} />
              )}
            </figure>

            {series.status === 'calculated' && <MeasureEvidence measure={series} />}
            <TrendTable trends={trends} />
          </>
        ) : (
          <div className="empty-state trends-empty">
            <p className="empty-state-title">No periods to show</p>
            <p>
              Trends need a date column with dates written YYYY-MM-DD. Choose the date column above, or check the notes
              about dates.
            </p>
          </div>
        )}

        <details className="disclosure">
          <summary>How dates and numbers are read</summary>
          <p>{trends.date_rule}</p>
          <p>{trends.number_rule}</p>
        </details>
      </div>
    </>
  )
}

type TrendControlsProps = { columns: string[]; options: TrendOptions; disabled: boolean; onChange: (options: TrendOptions) => void }

function TrendControls({ columns, options, disabled, onChange }: TrendControlsProps) {
  return (
    <div className="trend-controls">
      <fieldset className="field">
        <legend>Group by</legend>
        <div className="segmented">
          {GRAINS.map((grain: Grain) => (
            <label key={grain} className="segment">
              <input
                type="radio"
                name="trend-grain"
                value={grain}
                checked={grain === options.grain}
                disabled={disabled}
                onChange={() => onChange({ ...options, grain })}
              />
              <span>{GRAIN_LABELS[grain]}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className="field">
        <label htmlFor="trend-date-column">Date column</label>
        <select
          id="trend-date-column"
          value={options.dateColumn}
          disabled={disabled}
          onChange={(event) => onChange({ ...options, dateColumn: event.target.value })}
        >
          <option value="">{columns.includes('order_date') ? 'Automatic (order_date)' : 'Automatic (no "order_date" column)'}</option>
          {columns.map((column) => (
            <option key={column} value={column}>
              {column}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

/** How many rows had a usable date, and why the others were left out. */
function DatedRows({ dated, grain, periodCount }: { dated: MetricResult; grain: Grain; periodCount: number }) {
  const included = dated.rows_included
  const excluded = dated.rows_excluded
  return (
    <div className="trend-coverage">
      {included !== null && excluded !== null && (
        <p className="metric-rows">
          {pluralize(periodCount, GRAIN_UNITS[grain])} from {formatCount(included)} of {pluralize(included + excluded, 'row')}
          {excluded > 0 ? ` (${formatCount(excluded)} without a usable date)` : ''}
          {dated.columns_used.length > 0 && (
            <>
              , dated by <code>{dated.columns_used[0]}</code>
            </>
          )}
        </p>
      )}
      <Notes notes={dated.notes} tone={dated.status === 'calculated' ? 'warning' : 'info'} />
    </div>
  )
}

function SeriesUnavailable({ series, label }: { series: TrendSeries; label: string }) {
  return (
    <div className="empty-state trends-empty">
      <p className="empty-state-title">{label} not available</p>
      <Notes notes={series.notes} tone="info" />
    </div>
  )
}

/** Every period and every trend: the chart's table twin, readable without hovering. */
function TrendTable({ trends }: { trends: SalesTrends }) {
  const rows = trendTable(trends)
  const presentations = Object.fromEntries(TREND_KEYS.map((key) => [key, describeTrendSeries(key, trends)])) as Record<
    TrendKey,
    ReturnType<typeof describeTrendSeries>
  >
  return (
    <div className="subsection">
      <h4 id="trend-table-heading">All periods ({formatCount(rows.length)})</h4>
      <div className="table-scroll trend-table-scroll" role="region" aria-labelledby="trend-table-heading" tabIndex={0}>
        <table className="data-table trend-table">
          <thead>
            <tr>
              <th scope="col">Period</th>
              {TREND_KEYS.map((key) => (
                <th key={key} scope="col" className="numeric">
                  {presentations[key].label}
                </th>
              ))}
              <th scope="col" className="numeric">
                Rows
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.start} className={row.rowCount === 0 ? 'is-empty' : undefined}>
                <th scope="row">{row.label}</th>
                {TREND_KEYS.map((key) => (
                  <td key={key} className="numeric">
                    <CellText cell={row.cells[key]} format={presentations[key].format} />
                  </td>
                ))}
                <td className="numeric num">{formatCount(row.rowCount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function CellText({ cell, format }: { cell: TrendCell; format: Parameters<typeof formatMetricValue>[1] }) {
  switch (cell.kind) {
    case 'value':
      return <span className="num">{formatMetricValue(cell.value, format).text}</span>
    case 'no-rows':
      return <span className="muted">No rows</span>
    case 'not-usable':
      return <span className="muted">No usable values</span>
    case 'unavailable':
      return <span className="muted">Not available</span>
  }
}
