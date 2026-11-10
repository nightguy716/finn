import type { AlertConfig, Feed } from './types'

const BASE = (import.meta.env.VITE_API_BASE || 'https://finn-r4y3.vercel.app').replace(/\/$/, '')

export type FeedQuery = {
  asOf: string
  hours: number
  movePct: number
  volumeN: number
}

async function getJson<T>(path: string, params: Record<string, string>, signal?: AbortSignal): Promise<T> {
  const url = new URL(path, BASE)
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value)
  let response: Response
  try {
    response = await fetch(url, { signal })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new Error('The briefing could not be loaded.')
  }
  if (!response.ok) throw new Error(`The briefing could not be loaded (${response.status}).`)
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
    },
    signal,
  )
}

export function fetchAlertConfig(signal?: AbortSignal): Promise<AlertConfig> {
  return getJson<AlertConfig>('/api/alerts/config', {}, signal)
}
