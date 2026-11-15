import type { SnapshotPoint } from '../types'
import { glanceFacts } from '../format'

export function Glance({ series }: { series: SnapshotPoint[] | undefined }) {
  const facts = uniqueFacts(glanceFacts(series))
  return (
    <section className="mt-4 overflow-hidden">
      <h2 className="text-[12px] font-medium tracking-[0.14em] text-mute uppercase">At a glance</h2>
      <ul className="mt-2 flex flex-col gap-3">
        {facts.map((fact) => (
          <li key={fact} className="break-words text-[15px] leading-snug">
            {fact}
          </li>
        ))}
      </ul>
    </section>
  )
}

function uniqueFacts(facts: string[]): string[] {
  const out: string[] = []
  for (const fact of facts) {
    const trimmed = fact.trim()
    if (!trimmed) continue
    const lower = trimmed.toLowerCase()
    if (out.some((existing) => existing.toLowerCase() === lower)) continue
    out.push(trimmed)
  }
  return out
}
