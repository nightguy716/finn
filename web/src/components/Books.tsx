import { useState } from 'react'
import { dayLabel } from '../format'
import type { Financials, MoneyLine, MoneyRatio } from '../types'

export function Books({ books, waiting }: { books: Financials | null; waiting: boolean }) {
  if (!books && waiting) {
    return <p className="mt-4 text-[14px] leading-snug text-mute">Reading the balance sheet.</p>
  }
  if (!books || books.status !== 'ready' || !books.balance_sheet || !books.cash) {
    if (!books) return null
    return <p className="mt-4 text-[14px] leading-snug text-mute">{books.message || 'No balance sheet was found for this company.'}</p>
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
        stripRatioEcho
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
        caveat={books.cash.label === 'Half-year' ? 'Half-year figure; cash flow can swing with inventory and working-capital timing.' : ''}
        periodLabel={books.cash.label}
        periodEnd={books.cash.end}
        stripFreeCashFlow
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
  caveat,
  periodLabel,
  periodEnd,
  stripFreeCashFlow = false,
  stripRatioEcho = false,
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
  caveat?: string
  periodLabel?: string
  periodEnd?: string
  stripFreeCashFlow?: boolean
  stripRatioEcho?: boolean
}) {
  const [open, setOpen] = useState(false)
  const cleaned = cleanTakeaway(takeaway, {
    flags,
    periodLabel,
    periodEnd,
    caveat,
    stripFreeCashFlow,
    stripRatioEcho,
  })
  const visibleRatios = ratios.filter(([, ratio]) => ratio)
  const sharedReason = sharedNotMeaningful(visibleRatios.map(([, ratio]) => ratio!))
  const summary = sharedReason && /not meaningful/i.test(cleaned) ? '' : cleaned
  const halfYearNote = uniqueCaveat(caveat, [summary, note, sharedReason, ...flags])

  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-card px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[12px] tracking-[0.14em] text-mute uppercase">{title}</h2>
        <button type="button" className="min-h-11 rounded-full px-2 text-[13px] text-accent" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {open ? 'Less' : 'More'}
        </button>
      </div>
      <p className="mt-1 break-words font-mono text-[12px] text-mute">{meta}</p>
      {summary ? <p className={`mt-1 break-words text-[15px] leading-snug ${open ? '' : 'line-clamp-2'}`}>{summary}</p> : null}
      {flags.length ? (
        <div className="mt-2 flex flex-col gap-2">
          {flags.map((flag) => (
            <p key={flag} className="break-words text-[14px] leading-snug text-fall">
              {flag}
            </p>
          ))}
        </div>
      ) : null}
      {visibleRatios.length ? (
        <div className="mt-2 flex flex-col gap-2">
          {sharedReason ? (
            <p className="break-words text-[14px] leading-snug text-mute">{sharedReason}</p>
          ) : (
            visibleRatios.map(([label, ratio, kind]) =>
              ratio ? (
                <p key={label} className="min-w-0 break-words text-[14px] leading-snug">
                  <span className="text-mute">{label}. </span>
                  {ratio.meaningful === false ? ratio.reason : shown(ratio, kind)}
                  {open ? <span className="mt-0.5 block text-[13px] text-mute">{ratio.definition}</span> : null}
                  {open && ratio.note ? <span className="mt-0.5 block text-[13px] text-mute">{ratio.note}</span> : null}
                </p>
              ) : null,
            )
          )}
        </div>
      ) : null}
      {halfYearNote ? <p className="mt-1 break-words text-[13px] leading-snug text-mute">{halfYearNote}</p> : null}
      {open ? (
        <div className="mt-2 flex min-w-0 flex-col gap-2 overflow-hidden">
          <ul className="flex min-w-0 flex-col gap-2">
            {lines.map((line) => (
              <LineRow key={line.key} line={line} />
            ))}
          </ul>
          {missing.length ? <p className="break-words text-[13px] leading-snug text-mute">Not in this filing: {missing.join(', ')}.</p> : null}
          {note ? <p className="break-words text-[13px] leading-snug text-mute">{note}</p> : null}
          {source ? (
            <a href={source} target="_blank" rel="noreferrer" className="text-[13px] text-accent underline decoration-accent/30 underline-offset-2">
              XBRL filing
            </a>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}

function LineRow({ line }: { line: MoneyLine }) {
  const [showTag, setShowTag] = useState(false)
  return (
    <li className="flex min-w-0 items-baseline justify-between gap-3 text-[15px]">
      <span className="min-w-0">
        <span className="break-words">{line.label}</span>
        {line.tag ? (
          <span className="mt-0.5 block">
            <button
              type="button"
              className="min-h-11 rounded-full px-0 text-left text-[12px] text-accent"
              aria-expanded={showTag}
              onClick={() => setShowTag((value) => !value)}
            >
              {showTag ? 'Hide tag' : 'Tag'}
            </button>
            {showTag ? <span className="mt-0.5 block break-all font-mono text-[11px] text-mute">{line.tag}</span> : null}
          </span>
        ) : null}
        {line.note ? <span className="mt-0.5 block break-words text-[12px] text-mute">{line.note}</span> : null}
      </span>
      <span className="shrink-0 text-right font-mono text-[14px] tabular-nums">
        {money(line.value)}
        {line.prior != null ? <span className="block text-[12px] text-mute">was {money(line.prior)}</span> : null}
      </span>
    </li>
  )
}

function cleanTakeaway(
  takeaway: string,
  options: {
    flags: string[]
    periodLabel?: string
    periodEnd?: string
    caveat?: string
    stripFreeCashFlow?: boolean
    stripRatioEcho?: boolean
  },
): string {
  let text = takeaway.trim()
  if (!text) return ''

  if (options.periodLabel && options.periodEnd) {
    const endIso = options.periodEnd.slice(0, 10)
    const endLabel = dayLabel(options.periodEnd)
    const periodPatterns = [
      new RegExp(`^${escapeRegExp(options.periodLabel)}\\s+to\\s+${escapeRegExp(endIso)}\\.\\s*`, 'i'),
      new RegExp(`^${escapeRegExp(options.periodLabel)}\\s+to\\s+${escapeRegExp(endLabel)}\\.\\s*`, 'i'),
      new RegExp(`^${escapeRegExp(options.periodLabel)}\\s+${escapeRegExp(endLabel)}\\s+to\\s+${escapeRegExp(endLabel)}\\.\\s*`, 'i'),
    ]
    for (const pattern of periodPatterns) text = text.replace(pattern, '')
  }
  text = text.replace(/^(Half-year|Full-year)\s+to\s+\d{4}-\d{2}-\d{2}\.\s*/i, '')

  for (const flag of options.flags) {
    if (!flag) continue
    text = text.split(flag).join(' ')
  }

  if (options.stripFreeCashFlow) {
    text = text.replace(/Free cash flow is [^.]+\.\s*/gi, '')
  }

  if (options.stripRatioEcho) {
    text = text.replace(/Debt-to-equity is [^.]+\.\s*/gi, '')
    text = text.replace(/Net debt is [^.]+\.\s*/gi, '')
  }

  if (options.caveat) text = text.split(options.caveat).join(' ')
  text = text.replace(/Half-year figure;[^.]+\.\s*/gi, '')

  return text.replace(/\s+/g, ' ').trim()
}

function uniqueCaveat(caveat: string | undefined, already: (string | undefined)[]): string {
  if (!caveat) return ''
  const lower = caveat.toLowerCase()
  for (const item of already) {
    if (item && item.toLowerCase().includes(lower)) return ''
  }
  return caveat
}

function sharedNotMeaningful(ratios: MoneyRatio[]): string {
  const reasons = ratios
    .filter((ratio) => ratio.meaningful === false && ratio.reason)
    .map((ratio) => ratio.reason!.trim())
  if (reasons.length < 2) return ''
  const first = reasons[0]
  return reasons.every((reason) => reason === first) ? first : ''
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
  const digits = Math.abs(value) >= 10 ? 0 : 2
  return value.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: 0 })
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
