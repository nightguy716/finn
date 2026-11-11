import { useState, type ReactNode } from 'react'
import { bandNote, dayLabel } from '../format'
import type { Ledger, LedgerRevision, LedgerRow } from '../types'
import { Glance } from './Glance'
import { CompanySnapshot } from './Snapshot'

const SCORED: { status: string; label: string; tone?: string }[] = [
  { status: 'delivered', label: 'Delivered' },
  { status: 'tracking_ahead', label: 'Tracking ahead' },
  { status: 'tracking_on_track', label: 'On track' },
  { status: 'tracking_behind', label: 'Tracking behind' },
  { status: 'partly', label: 'Partly' },
  { status: 'borderline', label: 'Borderline', tone: 'text-amber' },
  { status: 'missed', label: 'Missed' },
]

const UNVERIFIED = new Set(['not_scored', 'segment_level', 'low_confidence', 'not_checkable'])

export function LedgerView({ ledger }: { ledger: Ledger }) {
  const rows = ledger.rows ?? []
  const scored = SCORED.map((group) => ({
    ...group,
    rows: rows.filter((row) => row.status === group.status),
  })).filter((group) => group.rows.length > 0)
  const unverified = rows.filter((row) => UNVERIFIED.has(row.status))
  const pending = rows.filter((row) => row.status === 'pending')
  const longTerm = ledger.long_term_targets ?? []
  const scoredStatus = new Set(SCORED.map((group) => group.status))
  const revisions = rows.filter((row) => scoredStatus.has(row.status) && (row.revisions?.length ?? 0) > 1)
  const note = ledger.coverage?.note?.trim() ?? ''
  const verdict = ledger.verdict?.trim() ?? ''
  const coverage = ledger.coverage

  return (
    <div className="mt-4">
      {verdict && verdict !== note ? <p className="text-[15px] leading-snug">{verdict}</p> : null}
      {coverage ? (
        <p className="mt-2 inline-block border border-line px-2 py-1 font-mono text-[11px] text-mute">
          {coverage.transcripts_found} of {coverage.transcripts_of} transcripts, {coverage.quarters_with_results} quarters of results
        </p>
      ) : null}
      {note ? <p className="mt-2 text-[14px] leading-snug">{note}</p> : null}
      {!verdict && !note && scored.length === 0 ? (
        <p className="mt-2 text-[14px] leading-snug">No consolidated guidance in these transcripts can be checked.</p>
      ) : null}

      {ledger.snapshot ? <Glance series={ledger.snapshot.series} /> : null}
      {ledger.snapshot ? <CompanySnapshot snapshot={ledger.snapshot} /> : null}

      {scored.length ? (
        <div className="mt-5 flex flex-col gap-4">
          {scored.map((group) => (
            <section key={group.status}>
              <h2 className={`text-[11px] tracking-[0.14em] uppercase ${group.tone || 'text-mute'}`}>
                {group.label}
                <span className="ml-2 font-mono">{group.rows.length}</span>
              </h2>
              <div className="mt-2 flex flex-col gap-2">
                {group.rows.map((row) => (
                  <ScoredRow key={rowKey(row)} row={row} tone={group.tone} />
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : null}

      {revisions.length ? (
        <section className="mt-5">
          <h2 className="text-[11px] tracking-[0.14em] text-mute uppercase">Revisions</h2>
          <div className="mt-2 flex flex-col gap-3">
            {revisions.map((row) => (
              <div key={rowKey(row)} className="border border-line bg-card px-3 py-2">
                <p className="text-[13px] leading-snug">{row.promise}</p>
                <ol className="mt-2 border-l border-line pl-3">
                  {(row.revisions ?? []).map((step, index) => (
                    <li key={`${step.date}-${index}`} className="pb-2">
                      <p className="font-mono text-[11px] text-mute tabular-nums">{step.date ? dayLabel(step.date) : 'Date not stated'}</p>
                      <p className="text-[13px]">
                        <span className="font-mono tabular-nums">{step.value}</span>
                        <span className="ml-2 text-mute">{step.superseded ? 'superseded' : changeWord(step)}</span>
                      </p>
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <Fold title="Guidance on record, not verifiable from filings" count={unverified.length} startOpen={scored.length === 0 && unverified.length > 0}>
        {unverified.map((row) => (
          <PlainRow key={rowKey(row)} row={row} />
        ))}
      </Fold>
      <Fold title="Not yet due" count={pending.length} startOpen={false}>
        {pending.map((row) => (
          <PlainRow key={rowKey(row)} row={row} />
        ))}
      </Fold>
      <Fold title="Long-term targets" count={longTerm.length} startOpen={false}>
        {longTerm.map((row) => (
          <PlainRow key={rowKey(row)} row={row} />
        ))}
      </Fold>
    </div>
  )
}

function ScoredRow({ row, tone }: { row: LedgerRow; tone?: string }) {
  const [open, setOpen] = useState(false)
  const arithmetic = (row.actual_detail || '').trim()
  const note = (row.note || '').trim()
  const borderline = row.status === 'borderline'
  return (
    <article className={`border bg-card ${borderline ? 'border-amber' : 'border-line'}`}>
      <button type="button" className="w-full px-3 py-2.5 text-left" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className="block text-[14px] leading-snug">{row.promise}</span>
        <span className="mt-1 flex items-baseline justify-between gap-3 font-mono text-[12px] tabular-nums">
          <span className={tone || ''}>
            {row.promised || '—'}
            <span className="mx-1 text-mute">against</span>
            {row.actual ?? '—'}
          </span>
          <span className="text-mute">{open ? 'Hide' : 'Source'}</span>
        </span>
      </button>
      <RowNotes row={row} pad />
      {borderline ? (
        <p className="px-3 pb-2.5 text-[12px] leading-snug text-amber">
          The figure is derived and sits within about 60 bps of the band edge.
        </p>
      ) : null}
      {open ? (
        <div className="border-t border-line px-3 py-2.5">
          {row.source_quote ? <p className="text-[13px] leading-snug">“{row.source_quote}”</p> : null}
          <p className="mt-2 text-[12px] text-mute">{row.speaker?.trim() ? `Speaker ${row.speaker.trim()}` : 'Speaker not named'}</p>
          <Source row={row} />
          {arithmetic ? <p className="mt-2 text-[13px] leading-snug">{arithmetic}</p> : null}
          {note && note !== arithmetic ? <p className="mt-1 text-[13px] leading-snug text-mute">{note}</p> : null}
        </div>
      ) : null}
    </article>
  )
}

function PlainRow({ row }: { row: LedgerRow }) {
  const ambiguous = ambiguousReadings(row)
  return (
    <article className="border-t border-line py-2.5">
      <p className="text-[14px] leading-snug">{row.promise}</p>
      {ambiguous ? (
        <>
          <p className="mt-1 text-[13px] leading-snug">{ambiguous}</p>
          <p className="mt-1 text-[13px] leading-snug text-mute">
            We do not score it because the quote does not define the margin, and the two readings disagree.
          </p>
        </>
      ) : (
        <p className="mt-1 text-[13px] leading-snug text-mute">{plainReason(row)}</p>
      )}
      {row.source_quote ? <p className="mt-1 text-[13px] leading-snug">“{row.source_quote}”</p> : null}
      <RowNotes row={row} />
      <Source row={row} />
    </article>
  )
}

function RowNotes({ row, pad = false }: { row: LedgerRow; pad?: boolean }) {
  const mapped = bandNote(row.source_quote || '', row.target_low, row.target_high)
  const definition = (row.definition_note || '').trim()
  if (!definition && !mapped) return null
  return (
    <div className={pad ? 'px-3 pb-2' : 'mt-1'}>
      {definition ? <p className="text-[12px] leading-snug text-mute">{definition}</p> : null}
      {mapped ? <p className={`text-[12px] leading-snug text-mute ${definition ? 'mt-1' : ''}`}>{mapped}</p> : null}
    </div>
  )
}

function ambiguousReadings(row: LedgerRow): string {
  const note = (row.note || '').trim()
  if (!/^definition ambiguous\b/i.test(note)) return ''
  return note.replace(/^definition ambiguous\.?\s*/i, '')
}

function plainReason(row: LedgerRow): string {
  const note = (row.note || '').trim()
  if (note) return note
  if (row.status === 'segment_level') return 'This figure is for a segment.'
  if (row.status === 'low_confidence') return 'Low confidence, so this row is not scored.'
  if (row.status === 'not_scored') return 'Not scored.'
  if (row.status === 'long_term') return 'A longer horizon. The quote does not name a year.'
  return 'No reason was stored for this row.'
}

function Source({ row }: { row: LedgerRow }) {
  const url = row.source_document || ''
  const name = fileName(url)
  return (
    <p className="mt-1 text-[12px]">
      {url ? (
        <a href={url} target="_blank" rel="noreferrer" className="text-accent underline decoration-accent/30 underline-offset-2">
          {name}
        </a>
      ) : (
        <span className="text-mute">No source document</span>
      )}
      {row.page ? <span className="text-mute"> · page {row.page}</span> : null}
    </p>
  )
}

function Fold({ title, count, startOpen, children }: { title: string; count: number; startOpen: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(startOpen)
  if (!count) return null
  return (
    <section className="mt-4 border border-line bg-card">
      <button type="button" className="flex w-full items-center justify-between gap-3 px-3 py-3 text-left" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className="text-[14px] leading-snug">
          {title}
          <span className="ml-2 font-mono text-[12px] text-mute">{count}</span>
        </span>
        <span className="font-mono text-[12px] text-mute">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open ? <div className="border-t border-line px-3">{children}</div> : null}
    </section>
  )
}

function changeWord(step: LedgerRevision): string {
  if (step.change === 'set') return 'set'
  if (step.change === 'raised') return 'raised'
  if (step.change === 'cut') return 'cut'
  if (step.change === 'maintained') return 'maintained'
  return step.change || ''
}

function fileName(url: string): string {
  const part = url.split('/').pop() || 'Filing'
  try {
    return decodeURIComponent(part)
  } catch {
    return part
  }
}

function rowKey(row: LedgerRow): string {
  return `${row.metric_key ?? ''}|${row.period_promised ?? ''}|${row.promise}|${row.status}`
}
