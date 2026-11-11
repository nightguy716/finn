import { useState } from 'react'
import type { Card, MetricLine } from '../types'
import { categoryLabel, clock, crore, dayLabel, delta, filingLinks, largeSwing, resultsTakeaway } from '../format'

function Sources({ card }: { card: Card }) {
  const fromSources = (card.sources ?? []).filter((source) => source.url)
  const raw = fromSources.length
    ? fromSources
    : (card.source_urls ?? []).filter(Boolean).map((url) => ({ subject: '', url }))
  const links = filingLinks(raw)
  if (!links.length) return <p className="mt-2 text-[12px] text-mute">No source link on this filing.</p>
  const onlyRaw = links.length === 1 && links[0].label.startsWith('XBRL')
  return (
    <div className="mt-2">
      <ul className="flex flex-col gap-1">
        {links.map((source) => (
          <li key={source.url}>
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="text-[12px] leading-snug text-accent underline decoration-accent/30 underline-offset-2"
            >
              {source.label}
            </a>
          </li>
        ))}
      </ul>
      {onlyRaw ? <p className="mt-1 text-[12px] leading-snug text-mute">This file is machine-readable data, not a page to read.</p> : null}
    </div>
  )
}

function CardMeta({ card, hero = false }: { card: Card; hero?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <p className="min-w-0">
        <span className="font-mono text-[12px] text-mute">{card.symbol}</span>
        <span className={`mt-0.5 block leading-tight font-medium ${hero ? 'text-[20px]' : 'text-[16px]'}`}>{card.company}</span>
      </p>
      <p className="shrink-0 font-mono text-[11px] tabular-nums text-mute">
        {dayLabel(card.timestamp)} {clock(card.timestamp)}
      </p>
    </div>
  )
}

function Levels({ line }: { line: MetricLine }) {
  const rows = [line.yoy, line.qoq, line.current]
  const max = Math.max(...rows.map((value) => (value == null ? 0 : Math.abs(value))), 1)
  return (
    <span className="flex w-9 shrink-0 flex-col justify-center gap-[3px]" aria-hidden="true">
      {rows.map((value, index) => (
        <span key={index} className="block h-[3px] bg-line">
          <span
            className={`block h-full ${index === 2 ? 'bg-accent' : 'bg-ink/30'}`}
            style={{ width: value == null || value === 0 ? '0%' : `${Math.max(8, (Math.abs(value) / max) * 100)}%` }}
          />
        </span>
      ))}
    </span>
  )
}

function Change({ label, line, which }: { label: string; line: MetricLine; which: 'qoq' | 'yoy' }) {
  const base = which === 'qoq' ? line.qoq : line.yoy
  const pct = which === 'qoq' ? line.qoq_pct : line.yoy_pct
  const change = delta(line.current, base, pct)
  return (
    <span className="inline-flex items-baseline gap-1 border border-line px-1 py-[1px] font-mono text-[10px] whitespace-nowrap tabular-nums">
      <span className="text-mute">{label}</span>
      <span className={change?.tone === 'up' ? 'text-accent' : change?.tone === 'down' ? 'text-fall' : 'text-ink'}>
        {change ? change.text : '—'}
      </span>
    </span>
  )
}

function Bars({ line }: { line: MetricLine }) {
  return (
    <span className="flex flex-col items-end">
      <Levels line={line} />
      <span className="mt-0.5 font-mono text-[9px] tracking-tight text-mute">yr ago – prev qtr – now</span>
    </span>
  )
}

function Detail({
  metrics,
  openKey,
  name,
}: {
  metrics: NonNullable<Card['body']['metrics']>
  openKey: string
  name: string
}) {
  const line = metrics[openKey as 'revenue' | 'ebitda' | 'pbt' | 'pat']
  if (!line) return null
  return (
    <div className="mt-2 flex items-center justify-between gap-3 border border-line px-2 py-2">
      <p className="text-[12px] text-mute">{name}</p>
      <Bars line={line} />
    </div>
  )
}

const RESULT_METRICS: { key: 'revenue' | 'ebitda' | 'pbt' | 'pat'; name: string; note?: string }[] = [
  { key: 'revenue', name: 'Revenue' },
  { key: 'ebitda', name: 'EBITDA', note: 'derived' },
  { key: 'pbt', name: 'PBT' },
  { key: 'pat', name: 'PAT' },
]

export function ResultsCard({ card, hero = false }: { card: Card; hero?: boolean }) {
  const [openKey, setOpenKey] = useState<string | null>(null)
  const metrics = card.body.metrics
  const reason = card.body.ebitda_reason?.trim()
  const hasEbitda = !reason && Boolean(metrics?.ebitda)
  const period = card.body.period ? `Quarter ended ${dayLabel(card.body.period)}` : card.headline
  const line = resultsTakeaway(metrics, hasEbitda)
  const swing = largeSwing(metrics, hasEbitda)
  const cells = RESULT_METRICS.filter((item) => item.key !== 'ebitda' || hasEbitda)
  return (
    <article id={card.id} className={`border bg-card px-3.5 py-2 ${hero ? 'border-accent' : 'border-line'}`}>
      <CardMeta card={card} hero={hero} />
      {hero ? <p className="mt-2 text-[11px] tracking-[0.14em] text-accent uppercase">Lead result</p> : null}
      <p className="mt-1 text-[12px] text-mute">
        Results · {period}
        {card.body.scope ? ` · ${card.body.scope}` : ''}
      </p>
      {line ? <p className="mt-2 text-[14px] leading-snug">{line}</p> : null}
      {swing ? (
        <p className="mt-1 text-[12px] leading-snug text-mute">
          Large swing. Check for one-off items; derived EBITDA includes exceptional items.
        </p>
      ) : null}
      {card.body.error ? <p className="mt-2 text-[13px]">{card.body.error}</p> : null}
      {metrics ? (
        <div className="mt-2">
          <p className="text-[11px] tracking-[0.08em] text-mute uppercase">₹ crore</p>
          <div className="mt-1 grid grid-cols-2 gap-1">
            {cells.map((item) => {
              const metric = metrics[item.key]
              const open = openKey === item.key
              return (
                <button
                  key={item.key}
                  type="button"
                  aria-expanded={open}
                  className={`border px-1.5 py-1 text-left ${open ? 'border-accent' : 'border-line'}`}
                  onClick={() => setOpenKey(open ? null : item.key)}
                >
                  <span className="block text-[11px] text-mute">
                    {item.name}
                    {item.note ? <span className="ml-1">{item.note}</span> : null}
                  </span>
                  <span className="mt-0.5 block font-mono text-[15px] tabular-nums">{metric ? crore(metric.current) : '—'}</span>
                  <span className="mt-1 flex flex-wrap gap-1">
                    {metric ? (
                      <>
                        <Change label="QoQ" line={metric} which="qoq" />
                        <Change label="YoY" line={metric} which="yoy" />
                      </>
                    ) : (
                      <span className="font-mono text-[11px] text-mute">—</span>
                    )}
                  </span>
                </button>
              )
            })}
          </div>
          {reason ? <p className="mt-1.5 text-[12px] leading-snug text-mute">{reason}</p> : null}
          {openKey ? (
            <Detail metrics={metrics} openKey={openKey} name={cells.find((item) => item.key === openKey)?.name ?? openKey} />
          ) : null}
        </div>
      ) : (
        <p className="mt-2 text-[13px] text-mute">Figures are not on this card.</p>
      )}
      <Sources card={card} />
    </article>
  )
}

export function ManagementCard({ card }: { card: Card }) {
  const [open, setOpen] = useState(false)
  const profile = card.body.profile?.trim()
  const missing = card.body.profile_note?.trim() || 'The disclosure has no biographical profile.'
  const kind = card.body.change_type ? sentenceCase(card.body.change_type) : categoryLabel(card.category)
  return (
    <article id={card.id} className="border border-line bg-card px-3.5 py-3">
      <CardMeta card={card} />
      <p className="mt-2 text-[11px] tracking-[0.14em] text-accent uppercase">{kind}</p>
      <h3 className="mt-1 text-[16px] leading-tight font-medium">{card.body.person || card.headline}</h3>
      {card.body.role ? <p className="mt-0.5 text-[13px] leading-snug">{card.body.role}</p> : null}
      <p className="mt-1 font-mono text-[12px] text-mute">
        {card.body.effective_date ? `Effective ${card.body.effective_date}` : 'Effective date not in the filing'}
      </p>
      {profile ? (
        <div className="mt-2">
          <button
            type="button"
            className="text-[13px] text-accent"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? 'Hide profile' : 'Profile from the filing'}
          </button>
          {open ? <p className="mt-1.5 text-[13px] leading-snug">{profile}</p> : null}
        </div>
      ) : (
        <p className="mt-2 text-[13px] text-mute">{missing}</p>
      )}
      <Sources card={card} />
    </article>
  )
}

export function MaterialCard({ card }: { card: Card }) {
  const line = card.body.line?.trim() || card.headline
  return (
    <article id={card.id} className="border border-line bg-card px-3.5 py-3">
      <CardMeta card={card} />
      <p className="mt-2 text-[11px] tracking-[0.14em] text-accent uppercase">{categoryLabel(card.category)}</p>
      <p className="mt-1.5 text-[14px] leading-snug">{line}</p>
      <Sources card={card} />
    </article>
  )
}

function sentenceCase(value: string): string {
  const text = value.replaceAll('_', ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function FilingCard({ card, hero = false }: { card: Card; hero?: boolean }) {
  if (card.category === 'results') return <ResultsCard card={card} hero={hero} />
  if (card.category === 'management_change') return <ManagementCard card={card} />
  return <MaterialCard card={card} />
}
