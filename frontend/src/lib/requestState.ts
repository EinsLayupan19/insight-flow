// The lifecycle of one request, shared by every data-loading hook.

/** `previous` keeps the last good result visible while refreshing or after a failed refresh. */
export type RequestState<T> =
  | { status: 'idle' }
  | { status: 'loading'; previous: T | null }
  | { status: 'success'; data: T }
  | { status: 'error'; message: string; previous: T | null }

export function latestData<T>(state: RequestState<T>): T | null {
  if (state.status === 'success') return state.data
  if (state.status === 'loading' || state.status === 'error') return state.previous
  return null
}

/** Start (or restart) a request, keeping whatever result was already shown. */
export function loadingFrom<T>(state: RequestState<T>): RequestState<T> {
  return { status: 'loading', previous: latestData(state) }
}

export function failedFrom<T>(state: RequestState<T>, message: string): RequestState<T> {
  return { status: 'error', message, previous: latestData(state) }
}
