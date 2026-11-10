import { useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import type { Alert, AlertConfig, Feed, LoadStatus } from '../types'
import { WINDOWS, plural, replayLine, shiftBack, shortDay } from '../format'
import { FilingCard } from './Cards'

export function Briefing({
  asOf,
  hours,
  move,
  volume,
  defaults,
  feed,
  status,
  error,
  onRetry,
  onAsOf,
  onHours,
  onOpenSettings,
  onOpenAlert,
}: {
  asOf: string
  hours: number
  move: number
  volume: number
  defaults: AlertConfig | null
  feed: Feed | null
  status: LoadStatus
  error: string | null
  onRetry: () => void
  onAsOf: (value: string) => void
  onHours: (hours: number) => void
  onOpenSettings: () => void
  onOpenAlert: (alert: Alert) => void
}) {
  const reduce = useReducedMotion()
  const [routineOpen, setRoutineOpen] = useState(false)
  const showFeed = feed && status !== 'loading'
  const start = status === 'ready' && feed ? feed.window_start : shiftBack(asOf, hours)
  const routineCount = feed?.routine.reduce((sum, row) => sum + row.count, 0) ?? 0
  const maxSeverity = Math.max(...(feed?.alerts ?? []).map((alert) => alert.severity), 1)

  return (
    <div className="pb-4">
      <header className="px-4 pt-4">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-[13px] font-medium tracking-[0.22em]">FINN</p>
          <button type="button" className="font-mono text-[12px] text-accent tabular-nums" onClick={onOpenSettings}>
            Alerts {trimNum(move)}% · {trimNum(volume)}×
          </button>
        </div>
        <div className="mt-3 flex items-center gap-1.5">
          {WINDOWS.map((item) => {
            const selected = item.hours === hours
            return (
              <button
                key={item.hours}
                type="button"
                aria-pressed={selected}
                className={`h-7 border px-2 font-mono text-[12px] ${selected ? 'border-accent text-accent' : 'border-line text-ink'}`}
                onClick={() => onHours(item.hours)}
              >
                {item.label}
              </button>
            )
          })}
          <label className="ml-auto">
            <span className="sr-only">As of</span>
            <input
              type="date"
              value={asOf}
              aria-label="As of"
              className="h-7 w-[132px] border border-line bg-transparent px-1.5 font-mono text-[12px]"
              onChange={(event) => {
                if (event.target.value) onAsOf(event.target.value)
              }}
            />
          </label>
        </div>
        <p className="mt-2 text-[12px] leading-snug text-mute">{replayLine(asOf, start)}</p>
        {defaults ? null : <p className="mt-1 text-[12px] text-mute">Reading alert defaults.</p>}
        {status === 'refreshing' ? <p className="mt-1 text-[12px] text-accent">Updating.</p> : null}
      </header>

      {status === 'loading' ? <Skeleton /> : null}
      {error ? (
        <div className="mx-4 mt-3 border border-line bg-card px-3 py-3">
          <p className="text-[14px] leading-snug">{error}</p>
          <button type="button" className="mt-2 text-[13px] text-accent" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : null}

      {showFeed && feed ? (
        <div className="mt-4">
          <section>
            <h2 className="px-4 text-[11px] tracking-[0.14em] text-mute uppercase">Movers</h2>
            {feed.alerts.length === 0 ? (
              <p className="mt-2 px-4 text-[13px] leading-snug text-mute">
                No move past {trimNum(move)}% or volume past {trimNum(volume)}× in this window.
              </p>
            ) : (
              <div className="mt-2 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                {feed.alerts.map((alert) => (
                  <button
                    key={`${alert.symbol}-${alert.date}`}
                    type="button"
                    className="w-[118px] shrink-0 border border-line bg-card px-2 py-1.5 text-left"
                    onClick={() => onOpenAlert(alert)}
                    aria-label={`${alert.symbol}, ${alert.date}, move ${alert.move_pct} percent, volume ${alert.volume_ratio ?? 'unknown'} times`}
                  >
                    <span className="block font-mono text-[12px]">{alert.symbol}</span>
                    <span className="mt-0.5 block font-mono text-[10px] text-mute tabular-nums">{shortDay(alert.date)}</span>
                    <span className="mt-0.5 flex items-baseline justify-between font-mono text-[12px] tabular-nums">
                      <span>{alert.move_pct.toFixed(1)}%</span>
                      <span>{alert.volume_ratio == null ? '—' : `${alert.volume_ratio.toFixed(1)}×`}</span>
                    </span>
                    <span className="mt-1.5 block h-[3px] bg-line" aria-hidden="true">
                      <span
                        className="block h-full bg-accent"
                        style={{ width: `${Math.max(6, (alert.severity / maxSeverity) * 100)}%` }}
                      />
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="mt-5 px-4">
            <h2 className="text-[11px] tracking-[0.14em] text-mute uppercase">
              {feed.cards.length ? plural(feed.cards.length, 'filing') : 'Filings'}
            </h2>
            {feed.cards.length === 0 && feed.alerts.length === 0 && routineCount === 0 ? (
              <p className="mt-3 text-[14px]">Nothing was filed in this window.</p>
            ) : null}
            <motion.div
              className="mt-2 flex flex-col gap-2"
              initial="hidden"
              animate="show"
              variants={{
                hidden: {},
                show: { transition: { staggerChildren: reduce ? 0 : 0.035 } },
              }}
            >
              {feed.cards.map((card) => (
                <motion.div
                  key={card.id}
                  variants={{
                    hidden: { opacity: reduce ? 1 : 0, y: reduce ? 0 : 6 },
                    show: { opacity: 1, y: 0, transition: { duration: reduce ? 0 : 0.2 } },
                  }}
                >
                  <FilingCard card={card} />
                </motion.div>
              ))}
            </motion.div>

            {routineCount > 0 ? (
              <div className="mt-2 border border-line bg-card">
                <button
                  type="button"
                  className="flex w-full items-center justify-between px-3.5 py-3 text-left"
                  aria-expanded={routineOpen}
                  onClick={() => setRoutineOpen((value) => !value)}
                >
                  <span className="text-[14px]">{plural(routineCount, 'routine filing')}</span>
                  <span className="font-mono text-[12px] text-mute">{routineOpen ? 'Hide' : 'Show'}</span>
                </button>
                {routineOpen ? (
                  <ul className="border-t border-line">
                    {feed.routine.map((row) => (
                      <li key={row.symbol} className="flex items-baseline justify-between gap-3 border-b border-line px-3.5 py-2 last:border-b-0">
                        <span className="text-[13px]">
                          <span className="font-mono text-[11px] text-mute">{row.symbol}</span>
                          <span className="ml-2">{row.company}</span>
                        </span>
                        <span className="font-mono text-[12px] tabular-nums">{row.count}</span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </div>
  )
}

function Skeleton() {
  return (
    <div className="mt-4 px-4" aria-hidden="true">
      <div className="h-3 w-16 animate-pulse bg-line" />
      <div className="mt-2 flex gap-2">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="h-[68px] w-[118px] shrink-0 animate-pulse bg-line" />
        ))}
      </div>
      <div className="mt-5 h-3 w-24 animate-pulse bg-line" />
      <div className="mt-2 flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, index) => (
          <div key={index} className="h-28 animate-pulse border border-line bg-line/70" />
        ))}
      </div>
    </div>
  )
}

function trimNum(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}
