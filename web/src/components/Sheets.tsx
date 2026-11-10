import { useEffect, useId, useState, type ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion'
import type { Alert, AlertConfig, Card } from '../types'
import { categoryLabel, shortDay } from '../format'

type SheetFrameProps = {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}

function SheetFrame({ open, title, onClose, children }: SheetFrameProps) {
  const reduce = useReducedMotion()
  const titleId = useId()
  const transition = reduce ? { duration: 0 } : { duration: 0.22, ease: 'easeOut' as const }

  useEffect(() => {
    if (!open) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open ? (
        <div className="absolute inset-0 z-20">
          <motion.button
            type="button"
            aria-label="Close"
            className="absolute inset-0 bg-ink/30"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={transition}
            onClick={onClose}
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            className="absolute inset-x-0 bottom-0 flex max-h-[78%] flex-col border-t border-line bg-card"
            initial={{ y: reduce ? 0 : '100%' }}
            animate={{ y: 0 }}
            exit={{ y: reduce ? 0 : '100%' }}
            transition={transition}
          >
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <h2 id={titleId} className="text-[15px] font-medium">
                {title}
              </h2>
              <button type="button" className="text-[13px] text-accent" onClick={onClose} autoFocus>
                Close
              </button>
            </div>
            <div className="min-h-0 overflow-y-auto px-4 py-3 pb-[max(12px,env(safe-area-inset-bottom))]">{children}</div>
          </motion.div>
        </div>
      ) : null}
    </AnimatePresence>
  )
}

export function AlertSheet({
  alert,
  cards,
  onClose,
  onJump,
}: {
  alert: Alert | null
  cards: Card[]
  onClose: () => void
  onJump: (id: string) => void
}) {
  const known = new Set(cards.map((card) => card.id))
  return (
    <SheetFrame open={alert != null} title={alert ? alert.symbol : 'Move'} onClose={onClose}>
      {alert ? (
        <div className="flex flex-col gap-3">
          <p className="text-[13px] text-mute">{alert.company}</p>
          <p className="font-mono text-[13px] tabular-nums">
            {shortDay(alert.date)} · close {alert.close.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </p>
          <p className="font-mono text-[13px] tabular-nums">
            Move {alert.move_pct.toFixed(1)}%
            {alert.volume_ratio == null ? ' · volume multiple unavailable' : ` · volume ${alert.volume_ratio.toFixed(2)}×`}
          </p>
          <p className="text-[12px] text-mute">Filings around this move.</p>
          <ul className="flex flex-col">
            {alert.events.map((event) => (
              <li key={event.id} className="border-t border-line py-2">
                <p className="text-[11px] tracking-[0.12em] text-accent uppercase">{categoryLabel(event.category)}</p>
                <p className="mt-0.5 text-[14px] leading-snug">{event.headline}</p>
                {known.has(event.id) ? (
                  <button type="button" className="mt-1 text-[12px] text-accent underline" onClick={() => onJump(event.id)}>
                    Show in the brief
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          {alert.events.length === 0 ? <p className="text-[14px]">No filings were attached to this move.</p> : null}
        </div>
      ) : null}
    </SheetFrame>
  )
}

export function SettingsSheet({
  open,
  move,
  volume,
  defaults,
  onClose,
  onCommit,
}: {
  open: boolean
  move: number
  volume: number
  defaults: AlertConfig | null
  onClose: () => void
  onCommit: (move: number, volume: number) => void
}) {
  const [draftMove, setDraftMove] = useState(move)
  const [draftVolume, setDraftVolume] = useState(volume)

  useEffect(() => {
    if (!open) return
    setDraftMove(move)
    setDraftVolume(volume)
  }, [open, move, volume])

  useEffect(() => {
    if (!open) return
    const id = window.setTimeout(() => {
      if (draftMove !== move || draftVolume !== volume) onCommit(draftMove, draftVolume)
    }, 400)
    return () => window.clearTimeout(id)
  }, [draftMove, draftVolume, open, move, volume, onCommit])

  return (
    <SheetFrame open={open} title="Alert thresholds" onClose={onClose}>
      <p className="text-[13px] leading-snug text-mute">
        A price move beyond this, or volume above this multiple of the recent average, shows in the strip.
      </p>
      <p className="mt-2 text-[12px] text-mute">
        {defaults
          ? `Default ${formatNum(defaults.move_pct)}% and ${formatNum(defaults.volume_n)}×.`
          : 'Reading the defaults.'}
      </p>
      <label className="mt-4 block">
        <span className="flex items-baseline justify-between text-[13px]">
          Price move
          <span className="font-mono tabular-nums">{formatNum(draftMove)}%</span>
        </span>
        <input
          className="mt-2"
          type="range"
          min={1}
          max={15}
          step={0.5}
          value={draftMove}
          aria-valuetext={`${formatNum(draftMove)} percent`}
          onChange={(event) => setDraftMove(Number(event.target.value))}
        />
      </label>
      <label className="mt-4 block">
        <span className="flex items-baseline justify-between text-[13px]">
          Volume multiple
          <span className="font-mono tabular-nums">{formatNum(draftVolume)}×</span>
        </span>
        <input
          className="mt-2"
          type="range"
          min={1}
          max={10}
          step={0.5}
          value={draftVolume}
          aria-valuetext={`${formatNum(draftVolume)} times`}
          onChange={(event) => setDraftVolume(Number(event.target.value))}
        />
      </label>
      <p className="mt-3 text-[12px] text-mute">The strip updates from the live feed a moment after a slider moves.</p>
    </SheetFrame>
  )
}

function formatNum(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}
