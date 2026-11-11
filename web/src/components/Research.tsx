import { useEffect, useState } from 'react'
import { ApiError, fetchLedger } from '../api'
import type { Ledger, LedgerProgress, LedgerUsage } from '../types'
import { LedgerView } from './Ledger'

const PRESETS = ['MARICO', 'ASIANPAINT', 'TITAN', 'PIDILITIND']
const CACHED = ['MARICO', 'ASIANPAINT', 'TITAN', 'CGPOWER', 'DMART', 'PIDILITIND', 'WIPRO']
const RECENT_KEY = 'finn.recent'
const SYMBOL = /^[A-Z0-9&-]{1,20}$/

type Phase = 'idle' | 'running' | 'ready' | 'error' | 'limited'

export function Research({ onOpenMenu, onUsage }: { onOpenMenu: () => void; onUsage: (usage: LedgerUsage | null) => void }) {
  const [draft, setDraft] = useState('')
  const [symbol, setSymbol] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [recent, setRecent] = useState<string[]>(loadRecent)
  const [phase, setPhase] = useState<Phase>('idle')
  const [progress, setProgress] = useState<LedgerProgress | null>(null)
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [limited, setLimited] = useState(false)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!symbol) return
    const ctrl = new AbortController()
    let cancelled = false
    setPhase('running')
    setError(null)
    setLimited(false)

    const existing = ledger
    async function run() {
      let previous = ''
      let held: Ledger | null = null
      while (!cancelled) {
        try {
          const body = await fetchLedger(symbol, ctrl.signal)
          if (cancelled) return
          const next = body.ledger ?? null
          const step = body.progress ?? next?.progress ?? null
          if (next) {
            held = next
            setLedger(next)
          }
          if (step) setProgress(step)
          if (step?.stage === 'complete' && next) {
            setPhase('ready')
            onUsage(next.usage ?? null)
            return
          }
          if (!next && !step) throw new Error('The ledger came back in an unexpected shape.')
          const mark = `${step?.stage ?? ''}:${step?.done ?? 0}:${step?.total ?? 0}`
          if (mark === previous) throw new Error('The ledger stopped advancing.')
          previous = mark
        } catch (reason) {
          if (cancelled || (reason instanceof DOMException && reason.name === 'AbortError')) return
          if (reason instanceof ApiError && reason.code === 'daily_limit') {
            const arrived = held && (held.rows?.length || held.verdict) ? held : null
            const keep = arrived || (existing?.symbol === symbol ? existing : null)
            setLimited(true)
            if (keep) {
              setLedger(keep)
              setPhase('ready')
            } else setPhase('limited')
            return
          }
          setError(reason instanceof Error ? reason.message : 'This step failed.')
          setPhase('error')
          return
        }
      }
    }

    void run()
    return () => {
      cancelled = true
      ctrl.abort()
    }
  }, [symbol, attempt, onUsage])

  function openSymbol(raw: string) {
    const next = raw.trim().toUpperCase()
    if (!next) return
    if (!SYMBOL.test(next)) {
      setNotice('Use the NSE symbol: letters, numbers, and a hyphen if the ticker has one.')
      return
    }
    setNotice('')
    setDraft(next)
    setLedger(null)
    setProgress(null)
    setError(null)
    setLimited(false)
    setPhase('running')
    remember(next)
    if (next === symbol) setAttempt((value) => value + 1)
    else setSymbol(next)
  }

  function remember(next: string) {
    const stored = [next, ...recent.filter((item) => item !== next)].slice(0, 8)
    setRecent(stored)
    localStorage.setItem(RECENT_KEY, JSON.stringify(stored))
  }

  const extras = recent.filter((item) => !PRESETS.includes(item))
  const busy = phase === 'running'
  const transcripts = ledger?.coverage?.transcripts_found ?? null
  const fraction = barFraction(progress, busy, transcripts)

  return (
    <div className="px-4 pt-4 pb-6">
      <div className="flex items-center gap-2">
        <button type="button" className="flex h-7 w-7 items-center justify-center border border-line" aria-label="Menu" onClick={onOpenMenu}>
          <span className="flex flex-col gap-[3px]" aria-hidden="true">
            <span className="block h-px w-3.5 bg-ink" />
            <span className="block h-px w-3.5 bg-ink" />
            <span className="block h-px w-3.5 bg-ink" />
          </span>
        </button>
        <p className="text-[13px] font-medium tracking-[0.22em]">FINN</p>
      </div>
      <form
        className="mt-3 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          openSymbol(draft)
        }}
      >
        <label className="min-w-0 flex-1">
          <span className="sr-only">NSE symbol</span>
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value.toUpperCase())}
            placeholder="NSE symbol"
            aria-label="NSE symbol"
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            className="h-9 w-full border border-line bg-card px-2 font-mono text-[14px] uppercase"
          />
        </label>
        <button type="submit" className="h-9 border border-accent px-3 text-[13px] text-accent">
          Open
        </button>
      </form>
      <p className="mt-2 text-[12px] leading-snug text-mute">Any NSE ticker works, not only these four.</p>
      {notice ? <p className="mt-2 text-[13px]">{notice}</p> : null}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {PRESETS.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={symbol === item}
            className={`h-7 border px-2 font-mono text-[12px] ${symbol === item ? 'border-accent text-accent' : 'border-line'}`}
            onClick={() => openSymbol(item)}
          >
            {item}
          </button>
        ))}
      </div>
      {extras.length ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {extras.map((item) => (
            <button key={item} type="button" className="h-7 border border-line px-2 font-mono text-[12px] text-mute" onClick={() => openSymbol(item)}>
              {item}
            </button>
          ))}
        </div>
      ) : null}

      {limited ? (
        <div className="mt-3 w-full border border-line bg-card px-3 py-3">
          <p className="text-[14px] leading-snug">Daily free-tier limit reached. Cached companies still work.</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {CACHED.map((item) => (
              <button key={item} type="button" className="h-7 border border-line px-2 font-mono text-[12px]" onClick={() => openSymbol(item)}>
                {item}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {symbol && phase !== 'ready' && phase !== 'limited' ? (
        <div className="mt-4" aria-live="polite">
          <p className="text-[14px]">{progressLine(progress, busy, ledger?.coverage?.transcripts_found ?? null)}</p>
          <div className="mt-2 h-[3px] bg-line" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(fraction * 100)}>
            <div className="h-full bg-accent" style={{ width: `${Math.round(fraction * 100)}%` }} />
          </div>
          {error ? (
            <div className="mt-3 border border-line bg-card px-3 py-3">
              <p className="text-[14px] leading-snug">{error}</p>
              <p className="mt-1 text-[12px] text-mute">Retry continues from the step it stopped on.</p>
              <button type="button" className="mt-2 text-[13px] text-accent" onClick={() => setAttempt((value) => value + 1)}>
                Retry
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {phase === 'ready' && ledger ? <LedgerView key={symbol} ledger={ledger} /> : null}
    </div>
  )
}

function progressLine(progress: LedgerProgress | null, busy: boolean, transcripts: number | null): string {
  if (!progress) return 'Finding filings'
  const { stage, done, total } = progress
  if (stage === 'discover') {
    if (busy) return 'Reading results'
    return total ? `Found ${done} of ${total} transcripts` : 'Finding transcripts'
  }
  if (stage === 'series') {
    if (busy) return transcripts ? `Reading transcript 1 of ${transcripts}` : 'Reading transcript 1'
    return total ? `Reading results, ${done} of ${total} quarters` : 'Reading results'
  }
  if (stage === 'guidance') {
    const count = total || transcripts || 0
    const reading = busy ? Math.min(count || 1, done + 1) : Math.max(done, 1)
    return `Reading transcript ${reading} of ${count || '…'}`
  }
  if (stage === 'complete') return 'Done'
  return 'Reading the filings'
}

function barFraction(progress: LedgerProgress | null, busy: boolean, transcripts: number | null): number {
  if (!progress) return busy ? 0.08 : 0
  if (progress.stage === 'complete') return 1
  if (progress.stage === 'discover') return busy ? 0.3 : 0.16
  if (progress.stage === 'series') {
    const count = transcripts || 1
    return busy ? 0.3 + (1 / count) * 0.68 : 0.3
  }
  if (progress.stage === 'guidance') {
    const total = progress.total || transcripts || 1
    const done = Math.min(total, progress.done + (busy ? 1 : 0))
    return 0.3 + (done / total) * 0.68
  }
  return 0.08
}

function loadRecent(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') as unknown
    if (!Array.isArray(raw)) return []
    return raw.filter((item): item is string => typeof item === 'string' && SYMBOL.test(item)).slice(0, 8)
  } catch {
    return []
  }
}
