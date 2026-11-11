import type { LedgerUsage, MetricLine, SnapshotPoint } from './types'

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

export const WATCH = [
  { id: 'results', label: 'Results' },
  { id: 'm_and_a', label: 'Deals' },
  { id: 'management_change', label: 'Management changes' },
  { id: 'credit_rating', label: 'Credit rating' },
  { id: 'litigation', label: 'Litigation' },
  { id: 'fund_raise', label: 'Fund raising' },
] as const

export function watchLine(chosen: number, count: number): string {
  if (!chosen) return 'Choose categories under Watch for. Watched filings stay at the top.'
  if (count < 0) return 'Watched filings stay at the top.'
  if (!count) return 'Watched filings stay at the top. None in this window.'
  const noun = count === 1 ? 'filing' : 'filings'
  return `Watched filings stay at the top. ${count} ${noun} in this window.`
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

/** Same order the API uses: severity, then symbol, then date. */
export function orderAlerts<T extends { severity: number; symbol: string; date: string }>(alerts: T[]): T[] {
  return [...alerts].sort(
    (a, b) => b.severity - a.severity || a.symbol.localeCompare(b.symbol) || a.date.localeCompare(b.date),
  )
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

const XBRL_LABEL = 'XBRL data (raw, machine-readable)'

const SOURCE_RANK: Record<string, number> = {
  'Outcome of board meeting PDF': 0,
  'Investor presentation': 1,
  'NSE filing': 2,
  [XBRL_LABEL]: 3,
}

/** A filing link labelled by what it is, not by the raw NSE subject. */
export function sourceLabel(subject: string, url: string): string {
  const blob = `${subject} ${url}`.toLowerCase()
  if (blob.includes('xbrl') || url.toLowerCase().endsWith('.xml')) return XBRL_LABEL
  if (blob.includes('investor presentation') || blob.includes('investorpre')) return 'Investor presentation'
  if (blob.includes('outcome of board') || blob.includes('outcomeofbm') || blob.includes('outcomeoftheboard')) return 'Outcome of board meeting PDF'
  return 'NSE filing'
}

export function filingLinks(sources: { subject?: string; url: string }[]): { label: string; url: string }[] {
  const specific = new Map<string, { label: string; url: string }>()
  const generic: { label: string; url: string }[] = []
  const seenSubjects = new Set<string>()
  const seenUrls = new Set<string>()
  for (const source of sources) {
    const url = source.url?.trim()
    if (!url || seenUrls.has(url)) continue
    seenUrls.add(url)
    const subject = (source.subject || '').trim()
    const key = subject.toLowerCase()
    const label = sourceLabel(subject, url)
    if (label === 'NSE filing') {
      if (key && seenSubjects.has(key)) continue
      if (key) seenSubjects.add(key)
      generic.push({ label, url })
      continue
    }
    if (!specific.has(label)) specific.set(label, { label, url })
  }
  return [...specific.values(), ...generic].sort((a, b) => (SOURCE_RANK[a.label] ?? 9) - (SOURCE_RANK[b.label] ?? 9))
}

function yoyPhrase(name: string, line: MetricLine | undefined): string {
  if (!line) return ''
  const change = delta(line.current, line.yoy, line.yoy_pct)
  if (!change) return ''
  if (change.text.endsWith('%')) return `${name} ${change.text} YoY`
  return `${name} ${change.text}`
}

function marginSentence(ebitda: MetricLine | undefined, revenue: MetricLine | undefined): string {
  if (!ebitda || ebitda.current == null || !revenue || revenue.current == null || revenue.current <= 0) return ''
  const now = (ebitda.current / revenue.current) * 100
  let pts = ''
  if (ebitda.yoy != null && revenue.yoy != null && revenue.yoy > 0) {
    const then = (ebitda.yoy / revenue.yoy) * 100
    const diff = now - then
    const sign = diff > 0 ? '+' : ''
    pts = `, ${sign}${diff.toFixed(1)} pts YoY`
  }
  return `EBITDA margin ${now.toFixed(1)}%${pts}`
}

/** One line from the quarter's own numbers. No model call. */
export function resultsTakeaway(metrics: Partial<Record<'revenue' | 'ebitda' | 'pbt' | 'pat', MetricLine>> | undefined, hasEbitda: boolean): string {
  if (!metrics) return ''
  const head = [yoyPhrase('Revenue', metrics.revenue), yoyPhrase('PAT', metrics.pat)].filter(Boolean)
  const margin = hasEbitda ? marginSentence(metrics.ebitda, metrics.revenue) : ''
  if (head.length && margin) return `${head.join(', ')}. ${margin}.`
  if (head.length) return `${head.join(', ')}.`
  return margin ? `${margin}.` : ''
}

function swingOn(line: MetricLine | undefined): boolean {
  if (!line || line.current == null) return false
  const pairs: [number | null, number | null][] = [
    [line.qoq, line.qoq_pct],
    [line.yoy, line.yoy_pct],
  ]
  return pairs.some(([base, pct]) => {
    if (base == null) return false
    if (base <= 0) return true
    return pct != null && Math.abs(pct) > 100
  })
}

export function largeSwing(metrics: Partial<Record<'revenue' | 'ebitda' | 'pbt' | 'pat', MetricLine>> | undefined, hasEbitda: boolean): boolean {
  if (!metrics) return false
  const lines = [metrics.revenue, metrics.pbt, metrics.pat, hasEbitda ? metrics.ebitda : undefined]
  return lines.some(swingOn)
}

/** Plain facts from the six-quarter series already on the ledger. No model call. */
export function glanceFacts(series: SnapshotPoint[] | undefined): string[] {
  const rows = series ?? []
  if (!rows.length) return ['No quarterly series is stored for this company.']
  const blanks = rows.filter((row) => row.revenue == null)
  const facts: string[] = []
  if (blanks.length || rows.length < 6) {
    const named = joinNames(blanks.map((row) => `the quarter ended ${dayLabel(row.period)}`))
    const sentence = named ? named.charAt(0).toUpperCase() + named.slice(1) : ''
    facts.push(
      blanks.length
        ? `The six-quarter series is incomplete. ${sentence} ${blanks.length === 1 ? 'has' : 'have'} no figures.`
        : 'The six-quarter series is incomplete.',
    )
  }
  const latest = rows.find((row) => row.revenue != null)
  const ago = latest ? rows.find((row) => row.period.slice(0, 10) === yearAgo(latest.period)) : undefined
  const revenue = movePhrase('Revenue', latest?.revenue, ago?.revenue)
  const direction = revenueDirection(rows)
  if (revenue && direction && blanks.length === 0 && rows.length >= 6) {
    facts.push(`${revenue}, and the six quarters are ${direction}.`)
  } else if (revenue && direction) {
    facts.push(`${revenue}, and the quarters with revenue are ${direction}.`)
  } else if (revenue) {
    facts.push(`${revenue}.`)
  } else if (blanks.length) {
    facts.push('Revenue, derived EBITDA margin, and PAT cannot be compared with a year ago.')
    if (direction) facts.push(`The quarters with revenue are ${direction}.`)
  }
  if (revenue) {
    const margin = marginPhrase(latest?.ebitda_margin_pct, ago?.ebitda_margin_pct)
    facts.push(margin ?? 'Derived EBITDA margin has no year-ago figure in this series.')
    const pat = movePhrase('PAT', latest?.pat, ago?.pat)
    facts.push(pat ? `${pat}.` : 'PAT growth from a year ago is not available.')
  }
  facts.push(swingPhrase(rows))
  return facts.slice(0, 5)
}

function yearAgo(period: string): string {
  const [year, month, day] = period.slice(0, 10).split('-')
  return `${Number(year) - 1}-${month}-${day}`
}

function movePhrase(label: string, current: number | null | undefined, base: number | null | undefined): string | null {
  const pct = current != null && base != null && base > 0 ? ((current - base) / base) * 100 : null
  const change = delta(current, base, pct)
  if (!change) return null
  if (change.text === 'flat') return `${label} is flat from a year ago`
  if (change.text.startsWith('+')) return `${label} is up ${change.text.slice(1)} from a year ago`
  if (change.text.startsWith('-')) return `${label} is down ${change.text.slice(1)} from a year ago`
  return `${label} ${change.text} from a year ago`
}

function marginPhrase(current: number | null | undefined, ago: number | null | undefined): string | null {
  if (current == null || ago == null) return null
  const bps = Math.round((current - ago) * 100)
  if (bps === 0) return 'Derived EBITDA margin is unchanged from a year ago.'
  const higher = bps > 0
  return `Derived EBITDA margin is ${Math.abs(bps)} bps ${higher ? 'higher' : 'lower'} than a year ago, so it is ${higher ? 'expanding' : 'compressing'}.`
}

function revenueDirection(rows: SnapshotPoint[]): string | null {
  const points = [...rows].reverse().filter((row) => row.revenue != null)
  if (points.length < 3) return null
  let ups = 0
  let downs = 0
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1].revenue ?? 0
    const current = points[index].revenue ?? 0
    if (current > previous) ups += 1
    else if (current < previous) downs += 1
  }
  const first = points[0].revenue ?? 0
  const last = points[points.length - 1].revenue ?? 0
  if (ups > downs && last > first) return 'rising'
  if (downs > ups && last < first) return 'falling'
  return 'uneven'
}

function swingPhrase(rows: SnapshotPoint[]): string {
  const losses = rows.filter((row) => row.pat != null && row.pat < 0)
  const oldest = [...rows].reverse()
  let swing = ''
  for (let index = 1; index < oldest.length; index += 1) {
    const before = oldest[index - 1]
    const after = oldest[index]
    if (bigMove(before.revenue, after.revenue) || bigMove(before.pat, after.pat)) {
      swing = `A large swing shows up between the quarter ended ${dayLabel(before.period)} and the quarter ended ${dayLabel(after.period)}.`
      break
    }
  }
  const loss =
    losses.length === 0
      ? ''
      : losses.length === 1
        ? `The quarter ended ${dayLabel(losses[0].period)} was a loss.`
        : `${losses.length} quarters were losses.`
  if (loss && swing) return `${loss} ${swing}`
  if (loss) return loss
  if (swing) return swing
  return 'No loss quarter, and no move past 100%.'
}

function bigMove(base: number | null | undefined, current: number | null | undefined): boolean {
  if (base == null || current == null) return false
  if (base <= 0 || current <= 0) return (base <= 0 && current > 0) || (base > 0 && current <= 0)
  return Math.abs((current - base) / base) > 1
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? ''
  if (names.length === 2) return `${names[0]} and ${names[1]}`
  return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`
}
