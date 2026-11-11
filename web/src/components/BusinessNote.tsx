import { useState } from 'react'
import type { BusinessNote, CitedFact, CitedItem } from '../types'

export function BusinessNoteView({ note }: { note: BusinessNote | null }) {
  const [open, setOpen] = useState(false)
  if (!note) return null
  if (note.status === 'partial') {
    return <p className="mt-4 text-[13px] leading-snug text-mute">Reading the annual report.</p>
  }
  if (note.status !== 'ready' || !note.snapshot) {
    return <p className="mt-4 text-[13px] leading-snug text-mute">{note.message || 'No annual report is available for this company.'}</p>
  }
  const fact = note.snapshot.does
  const segmentLine = (note.snapshot.segments ?? []).map((item) => (item.share ? `${item.name} ${item.share}` : item.name)).join(', ')
  const summary = fact?.text || note.snapshot.makes_money?.text || (segmentLine ? `Segments: ${segmentLine}` : '')
  if (!summary && !(note.snapshot.segments ?? []).length && !(note.snapshot.geographies ?? []).length) {
    return <p className="mt-4 text-[13px] leading-snug text-mute">The annual report did not state a business overview on the pages that were read.</p>
  }
  return (
    <section className="mt-4 border border-line bg-card px-3 py-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[11px] tracking-[0.14em] text-mute uppercase">From the annual report</h2>
        <button type="button" className="text-[12px] text-accent" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {open ? 'Less' : 'More'}
        </button>
      </div>
      <p className={`mt-1 text-[14px] leading-snug ${open ? '' : 'line-clamp-2'}`}>{summary}</p>
      {open ? (
        <div className="mt-2 flex flex-col gap-2">
          {note.snapshot.makes_money ? <Fact label="How it makes money" fact={note.snapshot.makes_money} /> : null}
          <ItemList label="Segments" items={note.snapshot.segments ?? []} />
          <ItemList label="Geographies" items={note.snapshot.geographies ?? []} />
          {fact ? <p className="font-mono text-[11px] text-mute">What it does, p. {fact.page}</p> : null}
          {note.url ? (
            <a href={note.url} target="_blank" rel="noreferrer" className="text-[12px] text-accent underline decoration-accent/30 underline-offset-2">
              Annual report{note.year ? ` ${note.year}` : ''}
            </a>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

function Fact({ label, fact }: { label: string; fact: CitedFact }) {
  return (
    <p className="text-[14px] leading-snug">
      <span className="text-mute">{label}. </span>
      {fact.text} <span className="font-mono text-[11px] text-mute">p. {fact.page}</span>
    </p>
  )
}

function ItemList({ label, items }: { label: string; items: CitedItem[] }) {
  if (!items.length) return null
  return (
    <div>
      <p className="text-[11px] tracking-[0.14em] text-mute uppercase">{label}</p>
      <ul className="mt-1 flex flex-col gap-1">
        {items.map((item) => (
          <li key={`${item.name}-${item.page}`} className="text-[14px] leading-snug">
            {item.name}
            {item.share ? <span className="font-mono text-[12px]"> {item.share}</span> : null}
            <span className="ml-1 font-mono text-[11px] text-mute">p. {item.page}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
