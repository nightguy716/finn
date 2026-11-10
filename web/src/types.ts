export type MetricLine = {
  current: number | null
  qoq: number | null
  yoy: number | null
  qoq_pct: number | null
  yoy_pct: number | null
}

export type FilingSource = {
  subject: string
  url: string
  timestamp?: string
}

export type CardBody = {
  line?: string
  period?: string
  scope?: string
  metrics?: Partial<Record<'revenue' | 'ebitda' | 'pbt' | 'pat', MetricLine>>
  ebitda_reason?: string
  person?: string | null
  role?: string | null
  change_type?: string | null
  effective_date?: string | null
  profile?: string | null
  profile_note?: string
  error?: string
  text_note?: string
}

export type Card = {
  id: string
  symbol: string
  company: string
  category: string
  priority: number
  timestamp: string
  headline: string
  body: CardBody
  source_urls?: string[]
  sources?: FilingSource[]
}

export type AlertEvent = {
  id: string
  category: string
  headline: string
}

export type Alert = {
  symbol: string
  company: string
  date: string
  close: number
  move_pct: number
  volume_ratio: number | null
  severity: number
  price_hit: boolean
  volume_hit: boolean
  events: AlertEvent[]
}

export type RoutineCompany = {
  symbol: string
  company: string
  count: number
}

export type Feed = {
  as_of: string
  window_hours: number
  window_start: string
  move_pct: number
  volume_n: number
  cards: Card[]
  routine: RoutineCompany[]
  alerts: Alert[]
  source?: string
}

export type AlertConfig = {
  move_pct: number
  volume_n: number
}

export type LoadStatus = 'loading' | 'ready' | 'refreshing' | 'error'
