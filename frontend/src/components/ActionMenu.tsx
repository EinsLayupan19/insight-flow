// A button that opens a short list of actions (the disclosure pattern: a toggle with aria-expanded
// and a list of ordinary buttons, so Tab and Enter work as everywhere else). Escape closes the list
// and returns focus to the toggle; a click outside closes it; choosing an action closes it.

import { useEffect, useId, useRef, useState } from 'react'
import { ChevronDownIcon } from './Icons'

export type MenuAction = {
  label: string
  onSelect: () => void
  danger?: boolean
}

type ActionMenuProps = {
  label: string
  actions: MenuAction[]
  variant: 'primary' | 'secondary'
  disabled?: boolean
  /** Which edge of the toggle the list lines up with. */
  align?: 'start' | 'end'
}

export function ActionMenu({ label, actions, variant, disabled = false, align = 'start' }: ActionMenuProps) {
  const [open, setOpen] = useState(false)
  // Opened from the keyboard: show the list at once (keyboard actions are never animated).
  const [instant, setInstant] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const toggleRef = useRef<HTMLButtonElement>(null)
  const listId = useId()

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setOpen(false)
      toggleRef.current?.focus()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  // A toggle that becomes disabled (another action started) also closes its list.
  if (open && disabled) setOpen(false)

  return (
    <div className="action-menu" ref={rootRef}>
      <button
        ref={toggleRef}
        type="button"
        className={`button-${variant} menu-toggle`}
        aria-expanded={open}
        aria-controls={listId}
        disabled={disabled}
        onClick={(event) => {
          setInstant(event.detail === 0) // detail is 0 for a click made with Enter or Space
          setOpen((isOpen) => !isOpen)
        }}
      >
        {label}
        <ChevronDownIcon size={16} className="menu-chevron" />
      </button>
      {open && (
        <ul id={listId} className={`menu-panel menu-${align}${instant ? ' is-instant' : ''}`}>
          {actions.map((action) => (
            <li key={action.label}>
              <button
                type="button"
                className={action.danger ? 'menu-item danger' : 'menu-item'}
                onClick={() => {
                  setOpen(false)
                  // The chosen item is about to disappear: keep keyboard focus on the toggle instead of losing it.
                  toggleRef.current?.focus()
                  action.onSelect()
                }}
              >
                {action.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
