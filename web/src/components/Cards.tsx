import { useState } from 'react'
import type { Card, MetricLine } from '../types'
import { categoryLabel, clock, crore, dayLabel, delta, shortDay } from '../format'

function Sources({ card }: { card: Card }) {
  const fromSources = (card.sources ?? []).filter((source) => source.url)
  const links = fromSources.length
    ? fromSources
    : (card.source_urls ?? []).filter(Boolean).map((url) => ({ subject: 'Filing', url }))
  if (!links.length) return <p className="mt-2 text-[12px] text-mute">No source link on this filing.</p>
  return (
    <ul className="mt-2 flex flex-col gap-1">
      {links.map((source) => (
        <li key={`${source.subject}-${source.url}`}>
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="text-[12px] leading-snug text-accent underline decoration-accent/30 underline-offset-2"
          >
            {source.subject || 'Filing'}
          </a>
        </li>
      ))}
    </ul>
  )
}

function CardMeta({ card }: { card: Card }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <p className="font-mono text-[11px] tracking-[0.04em] text-mute">{card.symbol}</p>
      <p className="font-mono text-[11px] tabular-nums text-mute">
        {shortDay(card.timestamp)} {clock(card.timestamp)}
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
    <span className="inline-flex items-baseline gap-1 border border-line px-1.5 py-[1px] font-mono text-[11px] tabular-nums">
      <span className="text-mute">{label}</span>
      <span className={change?.tone === 'up' ? 'text-accent' : 'text-ink'}>{change ? change.text : '—'}</span>
    </span>
  )
}

function Metric({ name, note, line }: { name: string; note?: string; line: MetricLine | undefined }) {
  if (!line) {
    return (
      <div className="border-t border-line py-2">
        <p className="text-[13px]">{name}</p>
        <p className="font-mono text-[13px] text-mute">—</p>
      </div>
    )
  }
  return (
    <div className="border-t border-line py-2">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[13px]">
          {name}
          {note ? <span className="ml-2 text-[11px] text-mute">{note}</span> : null}
        </p>
      </div>
      <div className="mt-1 flex items-center justify-between gap-3">
        <p className="font-mono text-[16px] tabular-nums">{crore(line.current)}</p>
        <span className="flex flex-col items-end">
          <Levels line={line} />
          <span className="mt-0.5 font-mono text-[9px] tracking-tight text-mute">ago · prev · now</span>
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1">
        <Change label="QoQ" line={line} which="qoq" />
        <Change label="YoY" line={line} which="yoy" />
      </div>
    </div>
  )
}

export function ResultsCard({ card, hero = false }: { card: Card; hero?: boolean }) {
  const metrics = card.body.metrics
  const reason = card.body.ebitda_reason?.trim()
  const period = card.body.period ? `Quarter ended ${dayLabel(card.body.period)}` : card.headline
  return (
    <article id={card.id} className={`border bg-card px-3.5 py-3 ${hero ? 'border-accent' : 'border-line'}`}>
      <CardMeta card={card} />
      {hero ? <p className="mt-2 text-[11px] tracking-[0.14em] text-accent uppercase">Lead result</p> : null}
      <h3 className={`leading-tight font-medium ${hero ? 'mt-1 text-[20px]' : 'mt-1 text-[16px]'}`}>{card.company}</h3>
      <p className="mt-1 text-[12px] text-mute">
        Results · {period}
        {card.body.scope ? ` · ${card.body.scope}` : ''}
      </p>
      {card.body.error ? <p className="mt-2 text-[13px]">{card.body.error}</p> : null}
      {metrics ? (
        <div className="mt-2">
          <p className="text-[11px] tracking-[0.08em] text-mute uppercase">₹ crore</p>
          <Metric name="Revenue" line={metrics.revenue} />
          {reason ? (
            <p className="border-t border-line py-2 text-[12px] leading-snug text-mute">{reason}</p>
          ) : (
            <Metric name="EBITDA" note="approx., derived" line={metrics.ebitda} />
          )}
          <Metric name="PBT" line={metrics.pbt} />
          <Metric name="PAT" line={metrics.pat} />
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
      <p className="mt-1 text-[12px] text-mute">{card.company}</p>
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
      <div className="mt-1 flex items-baseline gap-2">
        <p className="text-[11px] tracking-[0.14em] text-accent uppercase">{categoryLabel(card.category)}</p>
        <p className="text-[12px] text-mute">{card.company}</p>
      </div>
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
