export function WorkflowGuide() {
  return (
    <section className="card guide-card" aria-labelledby="guide-heading">
      <div className="card-header">
        <h2 id="guide-heading">How it works</h2>
      </div>
      <ol className="guide-steps">
        <li>
          <strong>Choose a CSV file.</strong> Comma-separated, UTF-8, with a header row.
        </li>
        <li>
          <strong>Validate.</strong> The server checks the file's structure and explains any problem.
        </li>
        <li>
          <strong>Review data quality.</strong> Missing values, duplicate rows, and column types, with line numbers.
        </li>
        <li>
          <strong>Review retail metrics.</strong> Only what your columns support, each with its definition.
        </li>
      </ol>
      <p className="guide-note">
        Metrics use columns named exactly <code>order_id</code>, <code>quantity</code>, <code>unit_price</code>, and{' '}
        <code>revenue</code>. Columns with other names can be mapped after the analysis.
      </p>
      <p className="guide-note">Files are analyzed in memory and not stored. Profit is not calculated yet.</p>
    </section>
  )
}
