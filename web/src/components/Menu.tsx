import { useState } from 'react'
import { PORTFOLIO } from '../portfolio'
import { SheetFrame } from './Sheets'

export type ThemeChoice = 'system' | 'light' | 'dark'
export type MenuPage = 'root' | 'portfolio' | 'method' | 'theme'

const STEPS = [
  {
    title: 'Briefing',
    body: 'What changed in your portfolio and why it matters.',
  },
  {
    title: 'Research',
    body: 'Type any NSE ticker and see what management promised against what they delivered.',
  },
  {
    title: 'Movers',
    body: 'Unusual price and volume days, linked to the filings around them.',
  },
]

export function IntroSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [step, setStep] = useState(0)
  const current = STEPS[step]
  const last = step === STEPS.length - 1
  return (
    <SheetFrame
      open={open}
      title="How FINN works"
      onClose={() => {
        setStep(0)
        onClose()
      }}
    >
      <p className="font-mono text-[11px] text-mute">
        {step + 1} of {STEPS.length}
      </p>
      <h3 className="mt-2 text-[18px] leading-tight font-medium">{current.title}</h3>
      <p className="mt-2 text-[15px] leading-snug">{current.body}</p>
      <div className="mt-4 flex gap-2">
        {step > 0 ? (
          <button type="button" className="h-9 border border-line px-3 text-[13px]" onClick={() => setStep((value) => value - 1)}>
            Back
          </button>
        ) : null}
        <button
          type="button"
          className="h-9 border border-accent px-3 text-[13px] text-accent"
          onClick={() => {
            if (last) {
              setStep(0)
              onClose()
            } else setStep((value) => value + 1)
          }}
        >
          {last ? 'Done' : 'Next'}
        </button>
      </div>
    </SheetFrame>
  )
}

export function MenuSheet({
  open,
  page,
  symbols,
  theme,
  onPage,
  onClose,
  onWorks,
  onToggle,
  onClear,
  onThresholds,
  onTheme,
}: {
  open: boolean
  page: MenuPage
  symbols: string[]
  theme: ThemeChoice
  onPage: (page: MenuPage) => void
  onClose: () => void
  onWorks: () => void
  onToggle: (symbol: string) => void
  onClear: () => void
  onThresholds: () => void
  onTheme: (theme: ThemeChoice) => void
}) {
  const title =
    page === 'portfolio' ? 'Portfolio' : page === 'method' ? 'Data and method' : page === 'theme' ? 'Theme' : 'Menu'
  return (
    <SheetFrame open={open} title={title} onClose={onClose}>
      {page === 'root' ? (
        <ul className="flex flex-col">
          <MenuRow label="How FINN works" onClick={onWorks} />
          <MenuRow label="Portfolio" detail={symbols.length ? `${symbols.length} selected` : 'All 18'} onClick={() => onPage('portfolio')} />
          <MenuRow label="Mover thresholds" onClick={onThresholds} />
          <MenuRow label="Data and method" onClick={() => onPage('method')} />
          <MenuRow label="Theme" detail={themeLabel(theme)} onClick={() => onPage('theme')} />
        </ul>
      ) : null}
      {page === 'portfolio' ? (
        <div>
          <button type="button" className="text-[13px] text-accent" onClick={() => onPage('root')}>
            Back
          </button>
          <p className="mt-2 text-[13px] leading-snug text-mute">Tap a company to show only its filings. Tap again to put it back.</p>
          <button type="button" className="mt-2 text-[13px] text-accent" onClick={onClear}>
            Show all 18
          </button>
          <ul className="mt-2">
            {PORTFOLIO.map((company) => {
              const on = symbols.includes(company.symbol)
              return (
                <li key={company.symbol} className="border-t border-line">
                  <button
                    type="button"
                    aria-pressed={on}
                    className="flex w-full items-baseline justify-between gap-3 py-2 text-left"
                    onClick={() => onToggle(company.symbol)}
                  >
                    <span>
                      <span className="font-mono text-[12px]">{company.symbol}</span>
                      <span className="mt-0.5 block text-[13px]">{company.company}</span>
                    </span>
                    <span className={`font-mono text-[12px] ${on ? 'text-accent' : 'text-mute'}`}>{on ? 'On' : 'Off'}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      ) : null}
      {page === 'method' ? (
        <div>
          <button type="button" className="text-[13px] text-accent" onClick={() => onPage('root')}>
            Back
          </button>
          <ul className="mt-3 flex flex-col gap-2 text-[14px] leading-snug">
            <li>Primary sources only. No broker notes and no news.</li>
            <li>Filings come from NSE.</li>
            <li>EBITDA is derived and excludes other income.</li>
            <li>Replay mode keeps the demo on a fixed day so the same filings are here whenever you open it.</li>
          </ul>
        </div>
      ) : null}
      {page === 'theme' ? (
        <div>
          <button type="button" className="text-[13px] text-accent" onClick={() => onPage('root')}>
            Back
          </button>
          <div className="mt-3 flex flex-col gap-2">
            {(['system', 'light', 'dark'] as const).map((choice) => (
              <button
                key={choice}
                type="button"
                aria-pressed={theme === choice}
                className={`h-9 border px-3 text-left text-[14px] ${theme === choice ? 'border-accent text-accent' : 'border-line'}`}
                onClick={() => onTheme(choice)}
              >
                {themeLabel(choice)}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </SheetFrame>
  )
}

function MenuRow({ label, detail, onClick }: { label: string; detail?: string; onClick: () => void }) {
  return (
    <li className="border-b border-line">
      <button type="button" className="flex w-full items-baseline justify-between gap-3 py-3 text-left" onClick={onClick}>
        <span className="text-[15px]">{label}</span>
        {detail ? <span className="font-mono text-[12px] text-mute">{detail}</span> : null}
      </button>
    </li>
  )
}

function themeLabel(theme: ThemeChoice): string {
  if (theme === 'system') return 'Match phone'
  if (theme === 'dark') return 'Dark'
  return 'Light'
}
