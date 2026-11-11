import { useState } from 'react'
import { dayLabel } from '../format'
import type { Financials, MoneyLine, MoneyRatio } from '../types'

export function Books({ books, waiting }: { books: Financials | null; waiting: boolean }) {
  if (!books && waiting) {
    return <p className="mt-4 text-[13px] leading-snug text-mute">Reading the balance sheet.</p>
  }
  if (!books || books.status !== 'ready' || !books.balance_sheet || !books.cash) {
    if (!books) return null
    return <p className="mt-4 text-[13px] leading-snug text-mute">{books.message || 'No balance sheet was found for this company.'}</p>
  }
  const scope = books.scope ? `${books.scope}. ` : ''
  return (
    <div className="mt-4 flex flex-col gap-3">
      <Panel
        title="Balance sheet"
        meta={`${scope}As at ${dayLabel(books.balance_sheet.as_of)}${books.balance_sheet.compared_with ? `, against ${dayLabel(books.balance_sheet.compared_with)}` : ''}`}
        takeaway={books.balance_sheet.takeaway}
        flags={books.balance_sheet.flags}
        lines={books.balance_sheet.lines}
        ratios={[
          ['Debt-to-equity', books.balance_sheet.ratios.debt_to_equity, 'ratio'],
          ['Net debt', books.balance_sheet.ratios.net_debt, 'crore'],
          ['Working capital', books.balance_sheet.ratios.working_capital, 'crore'],
        ]}
        missing={books.balance_sheet.missing}
        source={books.source_url}
      />
      <Panel
        title="Cash quality"
        meta={`${books.cash.label} ${dayLabel(books.cash.start)} to ${dayLabel(books.cash.end)}`}
        takeaway={books.cash.takeaway}
        flags={books.cash.flags}
        lines={books.cash.lines}
        ratios={[
          ['Free cash flow', books.cash.ratios.free_cash_flow, 'crore'],
          ['Cash conversion', books.cash.ratios.cash_conversion, 'ratio'],
        ]}
        missing={books.cash.missing}
        note={books.cash.receivables?.status === 'not_available' ? books.cash.receivables.reason : ''}
      />
    </div>
  )
}

function Panel({
  title,
  meta,
  takeaway,
  flags,
  lines,
  ratios,
  missing,
  source,
  note,
}: {
  title: string
  meta: string
  takeaway: string
  flags: string[]
  lines: MoneyLine[]
  ratios: [string, MoneyRatio | undefined, 'crore' | 'ratio'][]
  missing: string[]
  source?: string
  note?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <section className="border border-line bg-card px-3 py-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[11px] tracking-[0.14em] text-mute uppercase">{title}</h2>
        <button type="button" className="text-[12px] text-accent" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {open ? 'Less' : 'More'}
        </button>
      </div>
      <p className="mt-1 font-mono text-[11px] text-mute">{meta}</p>
      <p className={`mt-1 text-[14px] leading-snug ${open ? '' : 'line-clamp-2'}`}>{takeaway}</p>
      {open ? (
        <div className="mt-2 flex flex-col gap-2">
          {flags.map((flag) => (
            <p key={flag} className="text-[13px] leading-snug text-fall">
              {flag}
            </p>
          ))}
          <ul className="flex flex-col gap-1">
            {lines.map((line) => (
              <li key={line.key} className="flex items-baseline justify-between gap-3 text-[14px]">
                <span>
                  {line.label}
                  <span className="mt-0.5 block font-mono text-[10px] text-mute">{line.tag}</span>
                </span>
                <span className="shrink-0 text-right font-mono text-[13px] tabular-nums">
                  {money(line.value)}
                  {line.prior != null ? <span className="block text-[11px] text-mute">was {money(line.prior)}</span> : null}
                </span>
              </li>
            ))}
          </ul>
          {ratios.map(([label, ratio, kind]) =>
            ratio ? (
              <p key={label} className="text-[13px] leading-snug">
                <span className="text-mute">{label}. </span>
                {ratio.meaningful === false ? ratio.reason : shown(ratio, kind)}
                <span className="mt-0.5 block text-[12px] text-mute">{ratio.definition}</span>
              </p>
            ) : null,
          )}
          {missing.length ? <p className="text-[12px] leading-snug text-mute">Not in this filing: {missing.join(', ')}.</p> : null}
          {note ? <p className="text-[12px] leading-snug text-mute">{note}</p> : null}
          {source ? (
            <a href={source} target="_blank" rel="noreferrer" className="text-[12px] text-accent underline decoration-accent/30 underline-offset-2">
              XBRL filing
            </a>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

function shown(ratio: MoneyRatio, kind: 'crore' | 'ratio'): string {
  if (ratio.value == null) return 'not available'
  const current = kind === 'ratio' ? ratio.value.toFixed(2) : money(ratio.value)
  if (ratio.prior == null) return current
  const previous = kind === 'ratio' ? ratio.prior.toFixed(2) : money(ratio.prior)
  return `${current}, against ${previous}`
}

function money(value: number | null | undefined): string {
  if (value == null) return 'not available'
  return value.toLocaleString('en-IN', { maximumFractionDigits: 2 })
}
