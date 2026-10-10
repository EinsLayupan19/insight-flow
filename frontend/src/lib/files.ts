// Quick checks in the browser so obvious mistakes are caught before uploading.
// The backend repeats every check and has the final say (size limit, encoding, structure).

import { formatBytes } from './format'

/** The backend's default MAX_UPLOAD_MB. The server may be configured differently, so this only warns. */
export const DEFAULT_SERVER_LIMIT_MB = 10
const BYTES_PER_MB = 1024 * 1024

export type FileSelection = { file: File | null; error: string | null; warning: string | null }

export const EMPTY_SELECTION: FileSelection = { file: null, error: null, warning: null }

/** Check a picked or dropped set of files and keep the single CSV, if it passes. */
export function selectCsvFile(files: readonly File[]): FileSelection {
  if (files.length === 0) return EMPTY_SELECTION
  if (files.length > 1) {
    return { file: null, error: `${files.length} files were dropped. Choose one CSV file at a time.`, warning: null }
  }

  const [file] = files
  // Same rule as the backend: the name must end in .csv (any letter case).
  if (!file.name.toLowerCase().endsWith('.csv')) {
    return { file: null, error: `"${file.name}" is not a CSV file. Choose a file whose name ends in .csv.`, warning: null }
  }
  if (file.size === 0) {
    return { file: null, error: `"${file.name}" is empty (0 bytes). Choose a CSV file with a header row and data.`, warning: null }
  }

  const warning =
    file.size > DEFAULT_SERVER_LIMIT_MB * BYTES_PER_MB
      ? `This file is ${formatBytes(file.size)}. The server's default limit is ${DEFAULT_SERVER_LIMIT_MB} MB, so it may be rejected.`
      : null
  return { file, error: null, warning }
}
