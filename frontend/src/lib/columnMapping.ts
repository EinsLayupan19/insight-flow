// Column roles understood by POST /api/uploads/csv/metrics, and how a mapping resolves.
//
// Mirrors resolve_columns() in backend/app/analytics/retail_metrics.py: an explicit
// choice wins; otherwise a column named exactly like the role (case-sensitive) is
// used; otherwise the role has no column. The backend stays authoritative and
// rejects invalid mappings with HTTP 422. This copy only lets the UI prevent them.

export const METRIC_ROLES = ['order_id', 'quantity', 'unit_price', 'revenue'] as const
export type MetricRole = (typeof METRIC_ROLES)[number]

export const ROLE_LABELS: Record<MetricRole, string> = {
  order_id: 'Order ID',
  quantity: 'Quantity',
  unit_price: 'Unit price',
  revenue: 'Revenue',
}

/** Form field names accepted by the metrics endpoint (see backend/app/api/uploads.py). */
export const ROLE_FORM_FIELDS: Record<MetricRole, string> = {
  order_id: 'order_id_column',
  quantity: 'quantity_column',
  unit_price: 'unit_price_column',
  revenue: 'revenue_column',
}

/** Explicit column choices. A role that is absent (or empty) means "automatic". */
export type ColumnMapping = Partial<Record<MetricRole, string>>
export type ResolvedColumns = Record<MetricRole, string | null>

export function resolveColumns(columns: readonly string[], mapping: ColumnMapping): ResolvedColumns {
  const resolved = {} as ResolvedColumns
  for (const role of METRIC_ROLES) {
    const chosen = mapping[role]
    resolved[role] = chosen ? chosen : columns.includes(role) ? role : null
  }
  return resolved
}

/** Columns that would serve more than one role. The backend rejects these mappings. */
export function findConflicts(resolved: ResolvedColumns): string[] {
  const used = METRIC_ROLES.map((role) => resolved[role]).filter((column): column is string => column !== null)
  return [...new Set(used.filter((column, index) => used.indexOf(column) !== index))].sort()
}

/** The other role that `column` would serve, if any; used to disable select options. */
export function roleUsingColumn(resolved: ResolvedColumns, column: string, exceptRole: MetricRole): MetricRole | null {
  return METRIC_ROLES.find((role) => role !== exceptRole && resolved[role] === column) ?? null
}

/** Form fields for a mapping. Only explicit choices are sent; a missing field means "automatic". */
export function mappingFormFields(mapping: ColumnMapping): Record<string, string> {
  const fields: Record<string, string> = {}
  for (const role of METRIC_ROLES) {
    const chosen = mapping[role]
    if (chosen) fields[ROLE_FORM_FIELDS[role]] = chosen
  }
  return fields
}

/** Only the explicit choices, as the dataset API expects them (role -> column). */
export function explicitMapping(mapping: ColumnMapping): ColumnMapping {
  const explicit: ColumnMapping = {}
  for (const role of METRIC_ROLES) {
    const chosen = mapping[role]
    if (chosen) explicit[role] = chosen
  }
  return explicit
}

export function isSameMapping(a: ColumnMapping, b: ColumnMapping): boolean {
  return METRIC_ROLES.every((role) => (a[role] ?? '') === (b[role] ?? ''))
}

export function hasExplicitChoices(mapping: ColumnMapping): boolean {
  return METRIC_ROLES.some((role) => Boolean(mapping[role]))
}
