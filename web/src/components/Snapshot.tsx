import { crore, dayLabel } from '../format'
import type { Snapshot, SnapshotPoint } from '../types'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function CompanySnapshot({ snapshot }: { snapshot: Snapshot }) {
  const margin = ratio(snapshot.pat, snapshot.revenue)
  return (
    <section className="mt-4">
      <h2 className="text-[12px] tracking-[0.14em] text-mute uppercase">Snapshot</h2>
      <p className="mt-2 text-[13px] text-mute">
        {snapshot.latest_quarter ? `Quarter ended ${dayLabel(snapshot.latest_quarter)}` : 'Latest quarter'}
      </p>
      <dl className="mt-1">
        <Line label="Revenue" value={crore(snapshot.revenue)} unit="₹ crore" />
        <Line label="EBITDA margin" value={percent(snapshot.ebitda_margin_pct)} note="derived, excludes other income" />
        <Line label="PAT" value={crore(snapshot.pat)} unit="₹ crore" />
        {margin != null ? <Line label="PAT margin" value={percent(margin)} note="PAT ÷ revenue" /> : null}
      </dl>
      <p className="mt-3 text-[13px] text-mute">Trailing twelve months</p>
      {snapshot.ttm_note ? (
        <p className="mt-1 text-[14px] leading-snug">{snapshot.ttm_note}</p>
      ) : (
        <dl className="mt-1">
          <Line label="Revenue" value={crore(snapshot.ttm_revenue)} unit="₹ crore" />
          <Line label="PAT" value={crore(snapshot.ttm_pat)} unit="₹ crore" />
          <Line label="EBITDA margin" value={percent(snapshot.ttm_ebitda_margin_pct)} note="derived, excludes other income" />
        </dl>
      )}
      <QuarterChart points={[...(snapshot.series ?? [])].reverse().slice(-6)} />
    </section>
  )
}

function Line({ label, value, unit, note }: { label: string; value: string; unit?: string; note?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-line py-1.5">
      <dt className="text-[14px]">
        {label}
        {note ? <span className="mt-0.5 block text-[12px] text-mute">{note}</span> : null}
      </dt>
      <dd className="font-mono text-[15px] tabular-nums">
        {value}
        {unit && value !== '—' ? <span className="ml-1 text-[11px] text-mute">{unit}</span> : null}
      </dd>
    </div>
  )
}

function QuarterChart({ points }: { points: SnapshotPoint[] }) {
  if (!points.length) return null
  const width = 328
  const height = 128
  const padT = 8
  const padB = 22
  const inner = height - padT - padB
  const revenues = points.map((point) => point.revenue).filter((value): value is number => value != null && value > 0)
  const maxRevenue = Math.max(...revenues, 1)
  const margins = points.map((point) => point.ebitda_margin_pct).filter((value): value is number => value != null)
  const minMargin = margins.length ? Math.min(...margins) - 2 : 0
  const maxMargin = margins.length ? Math.max(...margins) + 2 : 1
  const slot = width / points.length
  const barW = Math.min(18, slot * 0.42)

  function yOf(margin: number) {
    const span = maxMargin - minMargin || 1
    return padT + inner - ((margin - minMargin) / span) * inner
  }

  const line = points
    .map((point, index) => {
      if (point.ebitda_margin_pct == null) return null
      const x = slot * index + slot / 2
      return `${x.toFixed(1)},${yOf(point.ebitda_margin_pct).toFixed(1)}`
    })
    .filter((value): value is string => value != null)
    .join(' ')

  return (
    <figure className="mt-3">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Six quarters of revenue, with the EBITDA margin as a line">
        {points.map((point, index) => {
          const revenue = point.revenue
          const h = revenue != null && revenue > 0 ? Math.max(2, (revenue / maxRevenue) * (inner - 8)) : 0
          const x = slot * index + (slot - barW) / 2
          return <rect key={point.period} x={x} y={padT + inner - h} width={barW} height={h} className="fill-accent/70" />
        })}
        {line ? <polyline points={line} fill="none" className="stroke-ink" strokeWidth="1.5" /> : null}
        {points.map((point, index) =>
          point.ebitda_margin_pct == null ? null : (
            <circle key={`${point.period}-dot`} cx={slot * index + slot / 2} cy={yOf(point.ebitda_margin_pct)} r="2.2" className="fill-ink" />
          ),
        )}
        {points.map((point, index) => (
          <text
            key={`${point.period}-label`}
            x={slot * index + slot / 2}
            y={height - 4}
            textAnchor="middle"
            className="fill-mute"
            fontSize="9"
            fontFamily="IBM Plex Mono, ui-monospace, monospace"
          >
            {tick(point.period)}
          </text>
        ))}
      </svg>
      <figcaption className="text-[12px] text-mute">Bars are revenue. The line is EBITDA margin, derived, and it excludes other income.</figcaption>
    </figure>
  )
}

function tick(iso: string): string {
  const [year, month] = iso.split('-').map(Number)
  if (!year || !month) return iso
  return `${MONTHS[month - 1]} ${String(year).slice(2)}`
}

function percent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value.toFixed(2)}%`
}

function ratio(part: number | null | undefined, whole: number | null | undefined): number | null {
  if (part == null || !whole) return null
  return (part / whole) * 100
}
