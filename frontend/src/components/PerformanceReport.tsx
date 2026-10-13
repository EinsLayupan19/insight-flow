// Product and category performance from the API (calculated live, or recorded in a dataset's
// history): the top groups as bars and every listed group in a table, with the API's own
// definitions, notes, and row counts. Rankings follow the API's tie-break rule.

import { useState, type ReactNode } from 'react'
import type { Breakdown, PerformanceGroup, ProductPerformance } from '../api/uploads'
import { formatCount, formatMetricValue, pluralize, type ValueFormat } from '../lib/format'
import type { MetricPresentation } from '../lib/metricDisplay'
import {
  DIMENSION_LABELS,
  describeRankKey,
  formatShare,
  rankGroups,
  rankOptions,
  summarizeRanking,
  type Dimension,
  type PerformanceOptions,
  type RankKey,
} from '../lib/performance'
import { latestData, type RequestState } from '../lib/requestState'
import { MeasureEvidence, Notes } from './Evidence'
import { Callout, LoadingState, StatusBadge } from './Feedback'
import { AlertIcon, Spinner } from './Icons'
import { PerformanceChart } from './PerformanceChart'

const CHART_GROUPS = 10

type PerformanceSectionProps = {
  state: RequestState<ProductPerformance>
  columns: string[]
  options: PerformanceOptions
  onChangeOptions: (options: PerformanceOptions) => void
  onRetry: () => void
}

/** The performance card on the analysis page. Column choices from Choose columns (Summary tab) apply here too. */
export function PerformanceSection({ state, columns, options, onChangeOptions, onRetry }: PerformanceSectionProps) {
  const data = latestData(state)
  const busy = state.status === 'loading'

  return (
    <section id="product-performance" className="card section-card" aria-labelledby="performance-heading" aria-busy={busy}>
      <header className="section-header">
        <h2 id="performance-heading">Products and categories</h2>
        <p>Revenue, quantity, and orders for each product and category, ranked. Labels are never merged or guessed.</p>
      </header>

      {state.status === 'error' && (
        <Callout
          tone="critical"
          title={data ? 'The rankings could not be updated' : 'The rankings could not be calculated'}
          action={
            <button type="button" className="button-secondary" onClick={onRetry}>
              Try again
            </button>
          }
        >
          {state.message}
          {data && ' The rankings below are from the last successful calculation.'}
        </Callout>
      )}

      {data !== null ? (
        <PerformanceView performance={data} columns={columns} options={options} busy={busy} onChangeOptions={onChangeOptions}>
          <p className="small muted">
            Order ID, quantity, unit price, and revenue columns follow <strong>Choose columns</strong> in the Summary tab.
          </p>
        </PerformanceView>
      ) : (
        state.status !== 'error' && <LoadingState>Ranking products and categories…</LoadingState>
      )}
    </section>
  )
}

type PerformanceViewProps = {
  performance: ProductPerformance
  columns: string[]
  /** The label columns behind the rankings shown. Changing one asks for a new calculation. */
  options: PerformanceOptions
  /** A new calculation is running: the rankings shown are dimmed until it finishes. */
  busy: boolean
  /** The options can't be changed right now (for example, another action is running). */
  disabled?: boolean
  onChangeOptions: (options: PerformanceOptions) => void
  children?: ReactNode
}

export function PerformanceView({ performance, columns, options, busy, disabled = false, onChangeOptions, children }: PerformanceViewProps) {
  const [chosen, setChosen] = useState<Dimension | null>(null)
  // Start on products, unless only the category breakdown could be calculated.
  const dimension: Dimension = chosen ?? (performance.products.status === 'calculated' || performance.categories.status !== 'calculated' ? 'product' : 'category')
  const breakdown = dimension === 'product' ? performance.products : performance.categories

  return (
    <>
      <LabelControls columns={columns} options={options} disabled={busy || disabled} onChange={onChangeOptions} />
      {children}
      {busy && (
        <p className="updating-note" role="status">
          <Spinner /> Recalculating rankings…
        </p>
      )}

      <div className={busy ? 'performance-body is-stale' : 'performance-body'}>
        <div className="segmented" role="radiogroup" aria-label="Breakdown">
          {(['product', 'category'] as const).map((key) => {
            const status = (key === 'product' ? performance.products : performance.categories).status
            return (
              <label key={key} className="segment">
                <input type="radio" name="performance-dimension" value={key} checked={key === dimension} onChange={() => setChosen(key)} />
                <span>
                  {DIMENSION_LABELS[key].title}
                  {status === 'unavailable' && <span className="segment-note"> (unavailable)</span>}
                </span>
              </label>
            )
          })}
        </div>

        {breakdown.status === 'calculated' ? (
          <BreakdownView key={dimension} breakdown={breakdown} performance={performance} />
        ) : (
          <div className="empty-state trends-empty">
            <p className="empty-state-title">{DIMENSION_LABELS[dimension].title} not available</p>
            <Notes notes={breakdown.notes} tone="info" />
          </div>
        )}

        <details className="disclosure">
          <summary>How labels and numbers are read</summary>
          <p>{performance.label_rule}</p>
          <p>{performance.number_rule}</p>
        </details>
      </div>
    </>
  )
}

type LabelControlsProps = { columns: string[]; options: PerformanceOptions; disabled: boolean; onChange: (options: PerformanceOptions) => void }

function LabelControls({ columns, options, disabled, onChange }: LabelControlsProps) {
  const select = (id: string, label: string, role: Dimension, value: string, change: (column: string) => PerformanceOptions) => (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} disabled={disabled} onChange={(event) => onChange(change(event.target.value))}>
        <option value="">{columns.includes(role) ? `Automatic (${role})` : `Automatic (no "${role}" column)`}</option>
        {columns.map((column) => (
          <option key={column} value={column} disabled={column === (role === 'product' ? options.categoryColumn : options.productColumn)}>
            {column}
          </option>
        ))}
      </select>
    </div>
  )
  // Changed rarely, so the selects sit in a disclosure; the coverage line below names the column in use.
  return (
    <details className="settings-disclosure">
      <summary>Change the product and category columns</summary>
      <div className="trend-controls">
        {select('performance-product-column', 'Product column', 'product', options.productColumn, (column) => ({ ...options, productColumn: column }))}
        {select('performance-category-column', 'Category column', 'category', options.categoryColumn, (column) => ({ ...options, categoryColumn: column }))}
      </div>
    </details>
  )
}

function BreakdownView({ breakdown, performance }: { breakdown: Breakdown; performance: ProductPerformance }) {
  const options = rankOptions(breakdown)
  const [chosenKey, setRankKey] = useState<RankKey>(breakdown.ranked_by ?? 'row_count')
  // A recalculation can cap the breakdown or drop a measure: never keep a ranking that is no longer offered.
  const rankKey = options.includes(chosenKey) ? chosenKey : options[0]
  const presentation = describeRankKey(rankKey, breakdown, performance)
  const ranked = rankGroups(breakdown.groups, rankKey)
  const names = DIMENSION_LABELS[breakdown.dimension]
  const included = breakdown.rows_included ?? 0
  const excluded = breakdown.rows_excluded ?? 0

  return (
    <div className="performance-breakdown">
      <div className="trend-coverage">
        <p className="metric-rows">
          {pluralize(breakdown.group_count, names.singular, names.plural)} from {formatCount(included)} of{' '}
          {pluralize(included + excluded, 'row')}
          {excluded > 0 ? ` (${formatCount(excluded)} with a blank ${names.singular})` : ''}, labels from{' '}
          <code>{breakdown.columns_used[0]}</code>
        </p>
        <Notes notes={breakdown.notes} tone="warning" />
      </div>

      <div className="rank-row">
        <div className="segmented" role="radiogroup" aria-label="Rank by">
          {options.map((key) => (
            <label key={key} className="segment">
              <input type="radio" name="performance-rank" value={key} checked={key === rankKey} onChange={() => setRankKey(key)} />
              <span>{describeRankKey(key, breakdown, performance).label}</span>
            </label>
          ))}
        </div>
        {breakdown.remaining !== null && (
          <p className="small muted">
            Only this ranking is offered: with {formatCount(breakdown.remaining.group_count)} more {names.plural} summarized, other
            rankings could miss the real top ones.
          </p>
        )}
      </div>

      <figure className="trend-figure">
        <figcaption className="trend-figure-title">
          Top {Math.min(CHART_GROUPS, ranked.length)} {names.plural} by {presentation.label.toLowerCase()}
        </figcaption>
        <PerformanceChart
          key={rankKey}
          groups={ranked.slice(0, CHART_GROUPS)}
          rankKey={rankKey}
          format={presentation.format}
          summary={summarizeRanking(breakdown, performance, rankKey, CHART_GROUPS)}
        />
      </figure>

      {rankKey !== 'row_count' && <MeasureEvidence measure={breakdown[rankKey]} />}
      <GroupTable breakdown={breakdown} performance={performance} ranked={ranked} />
    </div>
  )
}

/** Every listed group and every measure: the chart's table twin, plus the summary of groups past the cap. */
function GroupTable({ breakdown, performance, ranked }: { breakdown: Breakdown; performance: ProductPerformance; ranked: PerformanceGroup[] }) {
  const names = DIMENSION_LABELS[breakdown.dimension]
  const measures = (['revenue', 'quantity', 'order_count'] as const).filter((key) => breakdown[key].status === 'calculated')
  const formats: Record<(typeof measures)[number], MetricPresentation> = {
    revenue: describeRankKey('revenue', breakdown, performance),
    quantity: describeRankKey('quantity', breakdown, performance),
    order_count: describeRankKey('order_count', breakdown, performance),
  }
  const showShare = measures.includes('revenue')
  const isProduct = breakdown.dimension === 'product'
  const showRelated = isProduct ? performance.columns_used.category !== null : performance.columns_used.product !== null
  const { remaining } = breakdown

  return (
    <div className="subsection">
      <h4 id={`${breakdown.dimension}-table-heading`}>
        All {names.plural} ({formatCount(breakdown.groups.length)}
        {remaining ? ` listed of ${formatCount(breakdown.group_count)}` : ''})
      </h4>
      <div className="table-scroll trend-table-scroll" role="region" aria-labelledby={`${breakdown.dimension}-table-heading`} tabIndex={0}>
        <table className="data-table trend-table performance-table">
          <thead>
            <tr>
              <th scope="col" className="numeric">
                #
              </th>
              <th scope="col">{isProduct ? 'Product' : 'Category'}</th>
              {measures.map((key) => (
                <th key={key} scope="col" className="numeric">
                  {formats[key].label}
                </th>
              ))}
              {showShare && (
                <th scope="col" className="numeric">
                  Share
                </th>
              )}
              <th scope="col" className="numeric">
                Rows
              </th>
              {showRelated && <th scope="col">{isProduct ? 'Categories' : 'Products'}</th>}
            </tr>
          </thead>
          <tbody>
            {ranked.map((group, index) => (
              <tr key={group.label}>
                <td className="numeric num muted">{index + 1}</td>
                <th scope="row">
                  <span className="group-label">{group.label}</span>
                  {group.similar_labels.length > 0 && (
                    <span className="label-flag">
                      <AlertIcon size={13} className="tone-icon tone-warning" />
                      Similar: {group.similar_labels.join(', ')}
                    </span>
                  )}
                </th>
                {measures.map((key) => (
                  <td key={key} className="numeric">
                    <ValueText value={group[key]} format={formats[key].format} />
                  </td>
                ))}
                {showShare && <td className="numeric">{formatShare(group.revenue_share) ?? <span className="muted">Not available</span>}</td>}
                <td className="numeric num">{formatCount(group.row_count)}</td>
                {showRelated && (
                  <td>
                    {isProduct ? <CategoryList categories={group.categories} /> : formatCount(group.product_count ?? 0)}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
          {remaining && (
            <tfoot>
              <tr>
                <td />
                <th scope="row">{pluralize(remaining.group_count, `more ${names.singular}`, `more ${names.plural}`)} (summarized)</th>
                {measures.map((key) => (
                  <td key={key} className="numeric">
                    <ValueText value={remaining[key]} format={formats[key].format} />
                  </td>
                ))}
                {showShare && <td />}
                <td className="numeric num">{formatCount(remaining.row_count)}</td>
                {showRelated && <td />}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      {remaining && (
        <p className="small muted table-note">
          The summary row adds up every {names.singular} past the first {formatCount(breakdown.groups.length)}. Its order count is
          distinct orders across those {names.plural}.
        </p>
      )}
    </div>
  )
}

function ValueText({ value, format }: { value: number | null; format: ValueFormat }) {
  if (value === null) return <span className="muted">No usable values</span>
  return <span className="num">{formatMetricValue(value, format).text}</span>
}

function CategoryList({ categories }: { categories: string[] }) {
  if (categories.length === 0) return <span className="muted">None</span>
  if (categories.length === 1) return <>{categories[0]}</>
  return (
    <span className="label-flag-inline">
      <StatusBadge tone="warning">{categories.length} categories</StatusBadge> {categories.join(', ')}
    </span>
  )
}
