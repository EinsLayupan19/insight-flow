import { useEffect, useRef, useState, type DragEvent as ReactDragEvent, type ReactNode } from 'react'
import type { Analysis } from '../hooks/useCsvAnalysis'
import { latestData } from '../lib/requestState'
import type { FileSelection } from '../lib/files'
import { formatBytes } from '../lib/format'
import { AnalysisSteps } from './AnalysisSteps'
import { Callout } from './Feedback'
import { FileIcon, UploadIcon } from './Icons'

type UploadPanelProps = {
  selection: FileSelection
  analysis: Analysis | null
  saveToLibrary: boolean
  onSaveToLibraryChange: (save: boolean) => void
  onSelectFiles: (files: readonly File[]) => void
  onClearSelection: () => void
  onAnalyze: (file: File) => void
  onRetry: () => void
  onCancel: () => void
  /** Shown at the bottom of the card (help and links). */
  children?: ReactNode
}

export function UploadPanel({
  selection,
  analysis,
  saveToLibrary,
  onSaveToLibraryChange,
  onSelectFiles,
  onClearSelection,
  onAnalyze,
  onRetry,
  onCancel,
  children,
}: UploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const openPicker = () => inputRef.current?.click()
  usePreventDropNavigation()

  const file = selection.file
  // The analysis belongs to this panel only while it is for the file currently selected.
  const run = analysis !== null && file !== null && analysis.file === file ? analysis : null
  const running = run !== null && isRunning(run)
  // Cancel discards the analysis, so offer it only before any results are on screen
  // (not while metrics recalculate after a column-mapping change).
  const canCancel = running && run !== null && latestData(run.profile) === null && latestData(run.metrics) === null
  const validationError = run?.validation.status === 'error' ? run.validation.message : null
  const finished = run !== null && !running && run.validation.status === 'success'

  return (
    <section className="card upload-card" aria-labelledby="upload-heading">
      <div className="card-header">
        <h2 id="upload-heading">Upload a CSV file</h2>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        className="file-input"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          onSelectFiles(Array.from(event.target.files ?? []))
          event.target.value = '' // so choosing the same file again still triggers a change
        }}
      />

      {file === null ? (
        <>
          <Dropzone onFiles={onSelectFiles} onBrowse={openPicker} />
          {selection.error && <Callout tone="critical">{selection.error}</Callout>}
        </>
      ) : (
        <>
          <div className="file-row">
            <FileIcon size={22} className="file-row-icon" />
            <div className="file-row-meta">
              <span className="file-name">{file.name}</span>
              <span className="file-size">{formatBytes(file.size)}</span>
            </div>
            {!running && (
              <div className="file-row-actions">
                <button type="button" className="button-secondary" onClick={openPicker}>
                  Replace
                </button>
                <button type="button" className="button-ghost" onClick={onClearSelection} aria-label={`Remove ${file.name}`}>
                  Remove
                </button>
              </div>
            )}
          </div>

          {selection.warning && <Callout tone="warning">{selection.warning}</Callout>}

          {run === null && (
            <>
              <div className="storage-choice">
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={saveToLibrary}
                    onChange={(event) => onSaveToLibraryChange(event.target.checked)}
                    aria-describedby="storage-choice-help"
                  />
                  Save to my datasets
                </label>
                <p id="storage-choice-help" className="upload-note">
                  {saveToLibrary
                    ? "The file is stored on the InsightFlow server's disk, and every analysis is recorded in its history, until you delete it."
                    : 'The file is analyzed in memory and discarded. Nothing is stored.'}
                </p>
              </div>
              <div className="upload-actions">
                <button type="button" className="button-primary" onClick={() => onAnalyze(file)}>
                  {saveToLibrary ? 'Save and analyze' : 'Analyze file'}
                </button>
              </div>
            </>
          )}

          {run !== null && <AnalysisSteps analysis={run} />}

          {validationError && (
            <Callout
              tone="critical"
              title="The file could not be analyzed"
              action={
                <>
                  <button type="button" className="button-secondary" onClick={onRetry}>
                    Try again
                  </button>
                  <button type="button" className="button-ghost" onClick={openPicker}>
                    Choose a different file
                  </button>
                </>
              }
            >
              {validationError}
            </Callout>
          )}

          {canCancel && (
            <div className="upload-actions">
              <button type="button" className="button-secondary" onClick={onCancel}>
                Cancel
              </button>
            </div>
          )}

          {finished && (
            <div className="upload-actions">
              <button type="button" className="button-secondary" onClick={onClearSelection}>
                Analyze another file
              </button>
              <p className="upload-note">Results stay on this page until you analyze another file or clear them.</p>
            </div>
          )}
        </>
      )}
      {children}
    </section>
  )
}

function isRunning(analysis: Analysis): boolean {
  return [analysis.validation, analysis.profile, analysis.metrics].some((state) => state.status === 'loading')
}

function hasFiles(event: ReactDragEvent<HTMLElement>): boolean {
  return Array.from(event.dataTransfer.types).includes('Files')
}

function Dropzone({ onFiles, onBrowse }: { onFiles: (files: readonly File[]) => void; onBrowse: () => void }) {
  // Counting enter/leave events keeps the highlight steady while dragging over child elements.
  const [dragDepth, setDragDepth] = useState(0)

  return (
    <div
      className={dragDepth > 0 ? 'dropzone is-dragging' : 'dropzone'}
      onDragEnter={(event) => {
        if (!hasFiles(event)) return
        event.preventDefault()
        setDragDepth((depth) => depth + 1)
      }}
      onDragOver={(event) => {
        if (!hasFiles(event)) return
        event.preventDefault()
        event.dataTransfer.dropEffect = 'copy'
      }}
      onDragLeave={(event) => {
        if (hasFiles(event)) setDragDepth((depth) => Math.max(0, depth - 1))
      }}
      onDrop={(event) => {
        event.preventDefault()
        setDragDepth(0)
        onFiles(Array.from(event.dataTransfer.files))
      }}
    >
      <UploadIcon size={28} className="dropzone-icon" />
      <p className="dropzone-title">Drag and drop a CSV file here</p>
      <p className="dropzone-or">or</p>
      <button type="button" className="button-primary" onClick={onBrowse}>
        Choose a CSV file
      </button>
      <p className="dropzone-hint">Accepted: .csv files (comma-separated, UTF-8, with a header row)</p>
    </div>
  )
}

/** Dropping a file outside the drop zone would otherwise make the browser open it, leaving the app. */
function usePreventDropNavigation() {
  useEffect(() => {
    const prevent = (event: DragEvent) => {
      if (event.dataTransfer?.types.includes('Files')) event.preventDefault()
    }
    window.addEventListener('dragover', prevent)
    window.addEventListener('drop', prevent)
    return () => {
      window.removeEventListener('dragover', prevent)
      window.removeEventListener('drop', prevent)
    }
  }, [])
}
