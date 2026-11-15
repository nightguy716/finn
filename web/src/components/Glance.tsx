import type { SnapshotPoint } from '../types'
import { glanceFacts } from '../format'

export function Glance({ series }: { series: SnapshotPoint[] | undefined }) {
  const facts = glanceFacts(series)
  return (
    <section className="mt-4">
      <h2 className="text-[12px] font-medium tracking-[0.14em] text-mute uppercase">At a glance</h2>
      <ul className="mt-2 flex flex-col gap-3">
        {facts.map((fact) => (
          <li key={fact} className="text-[15px] leading-snug">
            {fact}
          </li>
        ))}
      </ul>
    </section>
  )
}
