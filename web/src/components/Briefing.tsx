import { useRef, useState } from 'react'
import { motion, useReducedMotion } from 'framer-motion'
import type { Alert, AlertConfig, Feed, LoadStatus } from '../types'
import { WINDOWS, dayLabel, orderAlerts, plural, watchLine, windowSummary } from '../format'
import { FilingCard } from './Cards'

export function Briefing({
  mode,
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
  onLive,
  onReplay,
  onHours,
  onOpenMenu,
  symbols,
  onOpenAlert,
  watch,
}: {
  mode: 'replay' | 'live'
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
  onLive: () => void
  onReplay: () => void
  onHours: (hours: number) => void
  onOpenMenu: () => void
  symbols: string[]
  onOpenAlert: (alert: Alert) => void
  watch: string[]
}) {
  const reduce = useReducedMotion()
  const dateRef = useRef<HTMLInputElement>(null)
  const [routineOpen, setRoutineOpen] = useState(false)
  const showFeed = feed && status !== 'loading'
  const routineCount = feed?.routine.reduce((sum, row) => sum + row.count, 0) ?? 0
  const watched = new Set(watch)
  const cards = feed
    ? [...feed.cards.filter((card) => watched.has(card.category)), ...feed.cards.filter((card) => !watched.has(card.category))]
    : []
  const watchedCount = cards.filter((card) => watched.has(card.category)).length
  const movers = feed ? orderAlerts(feed.alerts) : []
  const maxSeverity = Math.max(...movers.map((alert) => alert.severity), 1)
  const notRefreshed = mode === 'live' && feed?.stored === false

  return (
    <div className="pb-4">
      <header className="px-4 pt-4">
        <div className="flex items-start gap-2">
          <button type="button" className="mt-0.5 flex h-7 w-7 items-center justify-center border border-line" aria-label="Menu" onClick={onOpenMenu}>
            <span className="flex flex-col gap-[3px]" aria-hidden="true">
              <span className="block h-px w-3.5 bg-ink" />
              <span className="block h-px w-3.5 bg-ink" />
              <span className="block h-px w-3.5 bg-ink" />
            </span>
          </button>
          <div className="min-w-0">
            <p className="text-[13px] font-medium tracking-[0.22em]">FINN</p>
            <p className="mt-0.5 text-[13px] leading-snug text-mute">What changed in your portfolio, and why it matters.</p>
          </div>
        </div>
        <div className="mt-3 flex items-center gap-1.5">
          <button
            type="button"
            aria-pressed={mode === 'live'}
            className={`h-7 border px-2 text-[12px] ${mode === 'live' ? 'border-accent text-accent' : 'border-line text-ink'}`}
            onClick={onLive}
          >
            Live
          </button>
          <button
            type="button"
            aria-pressed={mode === 'replay'}
            className={`h-7 border px-2 text-[12px] ${mode === 'replay' ? 'border-accent text-accent' : 'border-line text-ink'}`}
            onClick={onReplay}
          >
            Replay
          </button>
        </div>
        <p className="mt-2 text-[12px] leading-snug text-mute">
          Replay is 6 Nov 2026, so the demo stays put. Live is today, from the morning refresh.
        </p>
        <p className="mt-1 text-[12px] leading-snug text-mute">{watchLine(watch.length, showFeed ? watchedCount : -1)}</p>
        <div className="mt-2 flex items-center gap-1.5">
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
          {mode === 'replay' ? (
            <div className="relative ml-auto">
              <button
                type="button"
                aria-label={`As of ${dayLabel(asOf)}`}
                className="h-7 border border-line px-1.5 font-mono text-[12px] tabular-nums"
                onClick={() => {
                  const input = dateRef.current
                  if (!input) return
                  if (typeof input.showPicker === 'function') input.showPicker()
                  else input.click()
                }}
              >
                {dayLabel(asOf)}
              </button>
              <label className="sr-only">
                As of
                <input
                  ref={dateRef}
                  type="date"
                  value={asOf}
                  aria-label="As of"
                  className="sr-only"
                  onChange={(event) => {
                    if (event.target.value) onAsOf(event.target.value)
                  }}
                />
              </label>
            </div>
          ) : (
            <p className="ml-auto font-mono text-[12px] tabular-nums text-mute">{dayLabel(asOf)}</p>
          )}
        </div>
        {symbols.length ? (
          <p className="mt-1 text-[12px] text-mute">
            Showing {symbols.length === 1 ? symbols[0] : `${symbols.length} companies`}. Change it from the menu.
          </p>
        ) : null}
        {showFeed && feed && !notRefreshed ? <p className="mt-1 text-[13px] leading-snug">{windowSummary(feed.cards, movers.length)}</p> : null}
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

      {showFeed && feed && notRefreshed ? (
        <div className="mx-4 mt-4">
          <p className="text-[14px] leading-snug">This window has not been refreshed yet.</p>
          <button type="button" className="mt-2 text-[13px] text-accent" onClick={onReplay}>
            Show the 6 Nov replay
          </button>
        </div>
      ) : null}

      {showFeed && feed && !notRefreshed ? (
        <div className="mt-4">
          <section>
            <h2 className="px-4 text-[11px] tracking-[0.14em] text-mute uppercase">Movers</h2>
            <p className="px-4 text-[12px] text-mute">
              Above {trimNum(feed.move_pct ?? move)}% or {trimNum(feed.volume_n ?? volume)}× volume.
            </p>
            {movers.length === 0 ? (
              <p className="mt-2 px-4 text-[13px] leading-snug text-mute">
                No move past {trimNum(move)}% or volume past {trimNum(volume)}× in this window.
              </p>
            ) : (
              <div className="mt-2 flex gap-2 overflow-x-auto px-4 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                {movers.map((alert) => (
                  <button
                    key={`${alert.symbol}-${alert.date}`}
                    type="button"
                    className="w-[118px] shrink-0 border border-line bg-card px-2 py-1.5 text-left"
                    onClick={() => onOpenAlert(alert)}
                    aria-label={`${alert.symbol}, ${dayLabel(alert.date)}, ${moverLabel(alert.signed_move_pct, alert.move_pct)}, volume ${alert.volume_ratio ?? 'unknown'} times the 20-day average`}
                  >
                    <span className="block font-mono text-[12px]">{alert.symbol}</span>
                    <span className="mt-0.5 block font-mono text-[10px] text-mute tabular-nums">{dayLabel(alert.date)}</span>
                    <span className={`mt-0.5 block font-mono text-[13px] tabular-nums ${moverTone(alert.signed_move_pct)}`}>
                      {moverLabel(alert.signed_move_pct, alert.move_pct)}
                    </span>
                    <span className="mt-0.5 block font-mono text-[10px] text-mute tabular-nums">
                      {alert.volume_ratio == null ? 'Volume n/a' : `${alert.volume_ratio.toFixed(1)}×`}
                      <span className="mt-px block tracking-normal">vs 20-day avg</span>
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
              {cards.length ? plural(cards.length, 'filing') : 'Filings'}
            </h2>
            {cards.length === 0 && feed.alerts.length === 0 && routineCount === 0 ? (
              <div className="mt-3">
                <p className="text-[14px]">Nothing was filed in this window.</p>
                {mode === 'live' ? (
                  <button type="button" className="mt-2 text-[13px] text-accent" onClick={onReplay}>
                    Show the 6 Nov replay
                  </button>
                ) : null}
              </div>
            ) : null}
            {hours < 72 && cards.length <= 3 ? (
              <div className="mt-2 border border-line bg-card px-3 py-2">
                <p className="text-[13px] leading-snug">
                  {cards.length === 0
                    ? 'Nothing material was filed in this short window.'
                    : `Only ${plural(cards.length, 'filing')} in this short window.`}
                </p>
                <button type="button" className="mt-1 text-[13px] text-accent" onClick={() => onHours(72)}>
                  Show 72 hours
                </button>
              </div>
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
              {cards.map((card) => (
                <motion.div
                  key={card.id}
                  variants={{
                    hidden: { opacity: reduce ? 1 : 0, y: reduce ? 0 : 6 },
                    show: { opacity: 1, y: 0, transition: { duration: reduce ? 0 : 0.2 } },
                  }}
                >
                  <FilingCard card={card} hero={card.id === heroId(cards)} watching={watched.has(card.category)} />
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

function moverLabel(signed: number | undefined, absolute: number): string {
  if (signed == null || Number.isNaN(signed)) return `${absolute.toFixed(1)}%`
  const arrow = signed > 0 ? '↑' : signed < 0 ? '↓' : ''
  const sign = signed > 0 ? '+' : ''
  return `${arrow} ${sign}${signed.toFixed(1)}%`.trim()
}

function moverTone(signed: number | undefined): string {
  if (signed == null || signed === 0) return ''
  return signed > 0 ? 'text-accent' : 'text-fall'
}

function heroId(cards: { id: string; category: string }[]): string | undefined {
  return (cards.find((card) => card.category === 'results') ?? cards[0])?.id
}

function trimNum(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}
