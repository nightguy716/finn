import { useEffect, useState } from 'react'
import { fetchLedger } from '../api'
import type { Ledger, LedgerProgress } from '../types'
import { LedgerView } from './Ledger'

const PRESETS = ['MARICO', 'ASIANPAINT', 'TITAN', 'PIDILITIND']
const RECENT_KEY = 'finn.recent'
const SYMBOL = /^[A-Z0-9&-]{1,20}$/

type Phase = 'idle' | 'running' | 'ready' | 'error'

export function Research() {
  const [draft, setDraft] = useState('')
  const [symbol, setSymbol] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [recent, setRecent] = useState<string[]>(loadRecent)
  const [phase, setPhase] = useState<Phase>('idle')
  const [progress, setProgress] = useState<LedgerProgress | null>(null)
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!symbol) return
    const ctrl = new AbortController()
    let cancelled = false
    setPhase('running')
    setError(null)

    async function run() {
      let previous = ''
      while (!cancelled) {
        try {
          const body = await fetchLedger(symbol, ctrl.signal)
          if (cancelled) return
          const next = body.ledger ?? null
          const step = body.progress ?? next?.progress ?? null
          if (next) setLedger(next)
          if (step) setProgress(step)
          if (step?.stage === 'complete' && next) {
            setPhase('ready')
            return
          }
          if (!next && !step) throw new Error('The ledger came back in an unexpected shape.')
          const mark = `${step?.stage ?? ''}:${step?.done ?? 0}:${step?.total ?? 0}`
          if (mark === previous) throw new Error('The ledger stopped advancing.')
          previous = mark
        } catch (reason) {
          if (cancelled || (reason instanceof DOMException && reason.name === 'AbortError')) return
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
  }, [symbol, attempt])

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
  const fraction = barFraction(progress, busy)

  return (
    <div className="px-4 pt-4 pb-6">
      <p className="text-[13px] font-medium tracking-[0.22em]">FINN</p>
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

      {symbol && phase !== 'ready' ? (
        <div className="mt-4" aria-live="polite">
          <p className="text-[14px]">{progressLine(progress, busy)}</p>
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

function progressLine(progress: LedgerProgress | null, busy: boolean): string {
  if (!progress) return 'Finding filings'
  const { stage, done, total } = progress
  if (stage === 'discover') return total ? `Found ${done} of ${total} transcripts` : 'Finding transcripts'
  if (stage === 'series') return total ? `Reading results, ${done} of ${total} quarters` : 'Reading the results'
  if (stage === 'guidance') {
    const reading = Math.min(total || 1, Math.max(1, done + (busy ? 1 : 0)))
    return `Reading transcript ${reading} of ${total || '…'}`
  }
  if (stage === 'complete') return 'Done'
  return 'Reading the filings'
}

function barFraction(progress: LedgerProgress | null, busy: boolean): number {
  if (!progress) return busy ? 0.08 : 0
  if (progress.stage === 'complete') return 1
  if (progress.stage === 'discover') return 0.16
  if (progress.stage === 'series') return 0.3
  if (progress.stage === 'guidance') {
    const total = progress.total || 1
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
