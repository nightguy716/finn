import type { AlertConfig, BusinessNote, Feed, LedgerResponse } from './types'

const BASE = (import.meta.env?.VITE_API_BASE || 'https://finn-r4y3.vercel.app').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export type FeedQuery = {
  asOf: string
  hours: number
  movePct: number
  volumeN: number
  symbols?: string[]
  stored?: boolean
}

async function getJson<T>(path: string, params: Record<string, string>, signal: AbortSignal | undefined, what: string): Promise<T> {
  const url = new URL(path, BASE)
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value)
  return fetchJson<T>(url, signal, what)
}

async function fetchJson<T>(url: URL, signal: AbortSignal | undefined, what: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, { signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error(`The ${what} could not be loaded.`)
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null
    if (response.status === 429 && body?.error === 'daily_limit') {
      throw new ApiError(429, 'daily_limit', 'Daily free-tier limit reached. Cached companies still work.')
    }
    throw new ApiError(response.status, body?.error || '', `The ${what} could not be loaded (${response.status}).`)
  }
  return response.json() as Promise<T>
}

export function fetchFeed(query: FeedQuery, signal?: AbortSignal): Promise<Feed> {
  return getJson<Feed>(
    '/api/feed',
    {
      as_of: query.asOf,
      hours: String(query.hours),
      move_pct: String(query.movePct),
      volume_n: String(query.volumeN),
      ...(query.symbols?.length ? { symbols: query.symbols.join(',') } : {}),
      ...(query.stored ? { stored: '1' } : {}),
    },
    signal,
    'briefing',
  )
}

export function fetchSnapshot(symbol: string, signal?: AbortSignal): Promise<BusinessNote> {
  return getJson<BusinessNote>('/api/snapshot', { symbol }, signal, 'annual report')
}

export function fetchAlertConfig(signal?: AbortSignal): Promise<AlertConfig> {
  return getJson<AlertConfig>('/api/alerts/config', {}, signal, 'alert defaults')
}

/** Query string for a ledger. Hyphens stay; & is percent-encoded so M&M is one symbol. */
export function ledgerPath(symbol: string): string {
  const params = new URLSearchParams()
  params.set('symbol', symbol)
  return `/api/ledger?${params.toString()}`
}

export async function fetchLedger(symbol: string, signal?: AbortSignal): Promise<LedgerResponse> {
  const url = new URL(ledgerPath(symbol), BASE)
  const body = await fetchJson<LedgerResponse>(url, signal, 'ledger')
  if (body.error && !body.ledger) {
    throw new Error(body.error === 'request failed' ? 'The exchange did not return this symbol.' : body.error)
  }
  return body
}
