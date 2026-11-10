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

export type LedgerProgress = {
  stage: string
  done: number
  total: number
}

export type Coverage = {
  transcripts_found: number
  transcripts_of: number
  quarters_with_results: number
  quarters_of: number
  note?: string
}

export type LedgerRevision = {
  date: string
  call_period?: string
  value: string
  change: string
  page?: number | null
  quote?: string
}

export type LedgerRow = {
  promise: string
  source_quote?: string
  page?: number | null
  source_document?: string
  speaker?: string
  period_promised?: string
  actual?: string | null
  actual_detail?: string
  promised?: string
  status: string
  note?: string
  scope?: string
  scope_name?: string
  metric_key?: string
  target_low?: number | null
  target_high?: number | null
  call_date?: string
  revisions?: LedgerRevision[]
}

export type SnapshotPoint = {
  period: string
  revenue: number | null
  ebitda: number | null
  ebitda_margin_pct: number | null
  pat: number | null
}

export type Snapshot = {
  latest_quarter?: string | null
  revenue?: number | null
  ebitda_margin_pct?: number | null
  pat?: number | null
  ttm_revenue?: number | null
  ttm_pat?: number | null
  ttm_ebitda_margin_pct?: number | null
  ttm_note?: string
  series?: SnapshotPoint[]
}

export type Ledger = {
  symbol?: string
  coverage?: Coverage
  snapshot?: Snapshot
  rows?: LedgerRow[]
  long_term_targets?: LedgerRow[]
  revisions?: { raised?: number; cut?: number; maintained?: number }
  verdict?: string
  progress?: LedgerProgress
}

export type LedgerResponse = {
  progress?: LedgerProgress
  ledger?: Ledger
  source?: string
  error?: string
}
