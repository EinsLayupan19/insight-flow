import { routeHref } from '../lib/route'

/** What a CSV file needs for each part of the analysis. Collapsed until asked for. */
export function FileRequirements() {
  return (
    <details className="disclosure file-requirements">
      <summary>What the file needs</summary>
      <ul className="evidence-list">
        <li>A .csv file: comma-separated, UTF-8, with a header row.</li>
        <li>
          Key numbers use columns named exactly <code>order_id</code>, <code>quantity</code>, <code>unit_price</code>, and{' '}
          <code>revenue</code>.
        </li>
        <li>
          Trends also need <code>order_date</code>, with dates written YYYY-MM-DD. Product rankings use <code>product</code>{' '}
          and <code>category</code>.
        </li>
        <li>Columns with other names can be chosen after the analysis, with Choose columns.</li>
      </ul>
      <p>
        Checked <strong>Save to my datasets</strong> keeps the file on the InsightFlow server and records every analysis
        until you delete it in <a href={routeHref({ page: 'datasets' })}>Datasets</a>. Unchecked, the file is analyzed in
        memory and discarded.
      </p>
    </details>
  )
}
