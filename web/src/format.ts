import type { LedgerUsage } from './types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export const WINDOWS = [
  { hours: 24, label: '24h' },
  { hours: 72, label: '72h' },
  { hours: 168, label: '7 days' },
] as const

const CATEGORIES: Record<string, string> = {
  results: 'Results',
  management_change: 'Management',
  m_and_a: 'M&A',
  fund_raise: 'Fund raise',
  litigation: 'Litigation',
  credit_rating: 'Rating',
  concall: 'Concall',
  board_meeting: 'Board',
  shareholder_meeting: 'Shareholders',
  dividend: 'Dividend',
  buyback: 'Buyback',
  order_contract: 'Order',
  insider: 'Insider',
  esop: 'ESOP',
  shareholding: 'Shareholding',
  routine: 'Routine',
}

export function categoryLabel(category: string): string {
  return CATEGORIES[category] ?? category.replaceAll('_', ' ')
}

export function dayLabel(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  if (!year || !month || !day) return iso
  return `${day} ${MONTHS[month - 1]} ${year}`
}

export function shortDay(iso: string): string {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  if (!year || !month || !day) return iso
  return `${day} ${MONTHS[month - 1]}`
}

export function clock(iso: string): string {
  const time = iso.split('T')[1] ?? ''
  return time.slice(0, 5)
}

export function crore(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  const digits = Math.abs(value - Math.round(value)) < 0.05 ? 0 : 2
  return new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)
}

export type Delta = { text: string; tone: 'up' | 'down' | 'flat' }

/** A percent against a negative or zero base is not a change an investor can use. */
export function delta(current: number | null | undefined, base: number | null | undefined, pct: number | null | undefined): Delta | null {
  if (current == null || base == null) return null
  if (base < 0 && current > 0) return { text: 'swung to profit', tone: 'up' }
  if (base > 0 && current < 0) return { text: 'swung to loss', tone: 'down' }
  if (base === 0 && current > 0) return { text: 'swung to profit', tone: 'up' }
  if (base === 0 && current < 0) return { text: 'swung to loss', tone: 'down' }
  if (base === 0) return { text: 'flat', tone: 'flat' }
  if (base < 0) return { text: 'still a loss', tone: 'down' }
  if (pct == null || Number.isNaN(pct)) return null
  const sign = pct > 0 ? '+' : ''
  const tone = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat'
  return { text: `${sign}${pct.toFixed(1)}%`, tone }
}

export function replayLine(asOf: string, _start?: string): string {
  return `Replay mode: showing ${dayLabel(asOf)} so the demo stays stable.`
}

/** Where a filing sits relative to the session, without saying the filing caused the move. */
export function relativeToMove(timestamp: string | undefined, moveDay: string): string {
  if (!timestamp) return 'Time not on the filing'
  const filed = timestamp.slice(0, 10)
  const time = clock(timestamp)
  const clocked = time ? `, ${time}` : ''
  if (filed === moveDay.slice(0, 10)) return `Same day as the move${clocked}`
  const days = Math.round((Date.parse(filed) - Date.parse(moveDay.slice(0, 10))) / 86_400_000)
  if (days === -1) return `The day before the move${clocked}`
  if (days === 1) return `The day after the move${clocked}`
  if (days < 0) return `${Math.abs(days)} days before the move${clocked}`
  if (Number.isNaN(days)) return 'Time not on the filing'
  return `${days} days after the move${clocked}`
}

export function shiftBack(asOf: string, hours: number): string {
  const [year, month, day] = asOf.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  date.setUTCHours(date.getUTCHours() - hours)
  return date.toISOString().slice(0, 10)
}

const BANDS: { phrase: string; low: number; high: number | null; read: string }[] = [
  { phrase: 'double-digit', low: 10, high: null, read: 'at least 10%' },
  { phrase: 'double digit', low: 10, high: null, read: 'at least 10%' },
  { phrase: 'high-teen', low: 17, high: 19, read: '17–19%' },
  { phrase: 'high teen', low: 17, high: 19, read: '17–19%' },
  { phrase: 'mid-teen', low: 13, high: 16, read: '13–16%' },
  { phrase: 'mid teen', low: 13, high: 16, read: '13–16%' },
  { phrase: 'low-teen', low: 10, high: 13, read: '10–13%' },
  { phrase: 'low teen', low: 10, high: 13, read: '10–13%' },
  { phrase: 'high single', low: 7, high: 9, read: '7–9%' },
]

/** When the quote uses a word and the row stores the band we mapped it to. */
export function bandNote(quote: string, low: number | null | undefined, high: number | null | undefined): string | null {
  const text = (quote || '').toLowerCase()
  for (const band of BANDS) {
    if (!text.includes(band.phrase)) continue
    const lowMatches = low != null && Math.abs(low - band.low) < 0.05
    const highMatches = band.high == null ? high == null : high != null && Math.abs(high - band.high) < 0.05
    if (lowMatches && highMatches) return `'${band.phrase}' read as ${band.read}`
  }
  return null
}

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

/** Counts already on the feed. No model call. */
export function windowSummary(cards: { category: string }[], movers: number): string {
  const results = cards.filter((card) => card.category === 'results').length
  const deals = cards.filter((card) => card.category === 'm_and_a' || card.category === 'fund_raise').length
  const management = cards.filter((card) => card.category === 'management_change').length
  const other = cards.length - results - deals - management
  const parts = [
    results ? plural(results, 'result') : '',
    deals ? plural(deals, 'deal') : '',
    management ? plural(management, 'management change') : '',
    other ? plural(other, 'other filing') : '',
    plural(movers, 'mover'),
  ].filter(Boolean)
  return `This window: ${parts.join(', ')}.`
}

/** Which model ran each ledger step. Shown in Data and method, not on the ledger itself. */
export function modelLine(usage: LedgerUsage | null | undefined): string {
  if (!usage) return ''
  const steps = [
    usage.guidance?.model ? `guidance on ${usage.guidance.model}` : '',
    usage.verify?.model ? `verification on ${usage.verify.model}` : '',
    usage.verdict?.model ? `the verdict on ${usage.verdict.model}` : '',
  ].filter(Boolean)
  if (!steps.length) return ''
  return `This ledger: ${steps.join(', ')}.`
}
