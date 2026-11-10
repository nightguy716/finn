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
  const abs = Math.abs(value)
  const digits = abs >= 1000 && Math.abs(value - Math.round(value)) < 0.05 ? 0 : 2
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

export function replayLine(asOf: string, start?: string): string {
  const end = dayLabel(asOf)
  const from = start ? dayLabel(start) : ''
  const span = from ? `${from} – ${end}` : end
  return `Replay of ${span}. The same filings, whenever you open it.`
}

export function shiftBack(asOf: string, hours: number): string {
  const [year, month, day] = asOf.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  date.setUTCHours(date.getUTCHours() - hours)
  return date.toISOString().slice(0, 10)
}

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}
