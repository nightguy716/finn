import { useCallback, useEffect, useState } from 'react'
import { fetchAlertConfig, fetchFeed } from './api'
import { Briefing } from './components/Briefing'
import { IntroSheet, MenuSheet, type MenuPage, type ThemeChoice } from './components/Menu'
import { Research } from './components/Research'
import { AlertSheet, SettingsSheet } from './components/Sheets'
import type { Alert, AlertConfig, Feed, LedgerUsage, LoadStatus } from './types'

const INTRO_KEY = 'finn.intro'
const THEME_KEY = 'finn.theme'
const WATCH_KEY = 'finn.watch'
const REPLAY_DAY = '2026-11-06'
type Tab = 'briefing' | 'research'
type BriefMode = 'replay' | 'live'

function loadWatch(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(WATCH_KEY) || '[]') as unknown
    return Array.isArray(raw) ? raw.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

function todayIST(): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date())
}

function loadTheme(): ThemeChoice {
  const stored = localStorage.getItem(THEME_KEY)
  if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  return 'dark'
}

export default function App() {
  const [tab, setTab] = useState<Tab>('briefing')
  const [mode, setMode] = useState<BriefMode>('replay')
  const [asOf, setAsOf] = useState(REPLAY_DAY)
  const [hours, setHours] = useState(72)
  const [move, setMove] = useState(5)
  const [volume, setVolume] = useState(2.5)
  const [defaults, setDefaults] = useState<AlertConfig | null>(null)
  const [feed, setFeed] = useState<Feed | null>(null)
  const [status, setStatus] = useState<LoadStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [symbols, setSymbols] = useState<string[]>([])
  const [alert, setAlert] = useState<Alert | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuPage, setMenuPage] = useState<MenuPage>('root')
  const [introOpen, setIntroOpen] = useState(() => localStorage.getItem(INTRO_KEY) !== 'seen')
  const [theme, setTheme] = useState<ThemeChoice>(loadTheme)
  const [usage, setUsage] = useState<LedgerUsage | null>(null)
  const [watch, setWatch] = useState<string[]>(loadWatch)
  const [pendingSymbol, setPendingSymbol] = useState<string | null>(null)

  useEffect(() => {
    const dark =
      theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0b1224' : '#f3f5fb')
    localStorage.setItem(THEME_KEY, theme)
    if (theme !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      document.documentElement.dataset.theme = media.matches ? 'dark' : 'light'
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', media.matches ? '#0b1224' : '#f3f5fb')
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [theme])

  useEffect(() => {
    const ctrl = new AbortController()
    fetchAlertConfig(ctrl.signal)
      .then((config) => {
        if (typeof config.move_pct === 'number' && typeof config.volume_n === 'number') setDefaults(config)
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
      })
    return () => ctrl.abort()
  }, [])

  useEffect(() => {
    const ctrl = new AbortController()
    setError(null)
    setStatus(feed ? 'refreshing' : 'loading')
    fetchFeed({ asOf, hours, movePct: move, volumeN: volume, symbols, stored: mode === 'live' }, ctrl.signal)
      .then((data) => {
        if (!Array.isArray(data.cards) || !Array.isArray(data.alerts) || !Array.isArray(data.routine)) {
          throw new Error('The briefing came back in an unexpected shape.')
        }
        setFeed(data)
        setStatus('ready')
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        setError(reason instanceof Error ? reason.message : 'The briefing could not be loaded.')
        setStatus('error')
      })
    return () => ctrl.abort()
    // feed is read only to choose the first-load skeleton. Including it would refetch forever.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asOf, hours, move, volume, symbols, attempt, mode])

  const onCommit = useCallback((nextMove: number, nextVolume: number) => {
    setMove(nextMove)
    setVolume(nextVolume)
  }, [])

  const closeAlert = useCallback(() => setAlert(null), [])
  const closeSettings = useCallback(() => setSettingsOpen(false), [])

  function jump(id: string) {
    setAlert(null)
    window.setTimeout(() => {
      document.getElementById(id)?.scrollIntoView({ block: 'start' })
    }, 30)
  }

  function researchCompany(symbol: string) {
    setAlert(null)
    setPendingSymbol(symbol)
    setTab('research')
  }

  return (
    <div className="flex h-dvh justify-center bg-desk text-ink">
      <div className="relative flex h-dvh w-full max-w-[390px] flex-col overflow-hidden bg-paper">
        <main className="min-h-0 flex-1 overflow-y-auto">
          {tab === 'briefing' ? (
            <Briefing
              mode={mode}
              asOf={asOf}
              hours={hours}
              move={move}
              volume={volume}
              defaults={defaults}
              feed={feed}
              status={status}
              error={error}
              onRetry={() => setAttempt((value) => value + 1)}
              onAsOf={setAsOf}
              onLive={() => {
                setMode('live')
                setAsOf(todayIST())
              }}
              onReplay={() => {
                setMode('replay')
                setAsOf(REPLAY_DAY)
              }}
              onHours={setHours}
              onOpenMenu={() => {
                setMenuPage('root')
                setMenuOpen(true)
              }}
              symbols={symbols}
              onOpenAlert={setAlert}
              onResearch={researchCompany}
              watch={watch}
            />
          ) : (
            <Research
              pendingSymbol={pendingSymbol}
              onPendingDone={() => setPendingSymbol(null)}
              onOpenMenu={() => {
                setMenuPage('root')
                setMenuOpen(true)
              }}
              onUsage={setUsage}
            />
          )}
        </main>
        <nav className="flex shrink-0 gap-3 border-t border-line bg-paper px-3 pb-[env(safe-area-inset-bottom)] pt-1" aria-label="Primary">
          <TabButton current={tab === 'briefing'} onClick={() => setTab('briefing')}>
            Briefing
          </TabButton>
          <TabButton current={tab === 'research'} onClick={() => setTab('research')}>
            Research
          </TabButton>
        </nav>
        <AlertSheet alert={alert} cards={feed?.cards ?? []} onClose={closeAlert} onJump={jump} onResearch={researchCompany} />
        <IntroSheet
          open={introOpen}
          onClose={() => {
            localStorage.setItem(INTRO_KEY, 'seen')
            setIntroOpen(false)
          }}
        />
        <MenuSheet
          open={menuOpen}
          page={menuPage}
          symbols={symbols}
          theme={theme}
          onPage={setMenuPage}
          onClose={() => setMenuOpen(false)}
          onWorks={() => {
            setMenuOpen(false)
            setIntroOpen(true)
          }}
          onToggle={(symbol) =>
            setSymbols((current) => (current.includes(symbol) ? current.filter((item) => item !== symbol) : [...current, symbol]))
          }
          onClear={() => setSymbols([])}
          onThresholds={() => {
            setMenuOpen(false)
            setSettingsOpen(true)
          }}
          onTheme={setTheme}
          usage={usage}
          watch={watch}
          onWatch={(id) =>
            setWatch((current) => {
              const next = current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
              localStorage.setItem(WATCH_KEY, JSON.stringify(next))
              return next
            })
          }
        />
        <SettingsSheet
          open={settingsOpen}
          move={move}
          volume={volume}
          defaults={defaults}
          onClose={closeSettings}
          onCommit={onCommit}
        />
      </div>
    </div>
  )
}

function TabButton({ current, onClick, children }: { current: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      className={`min-h-11 flex-1 rounded-full text-[15px] ${current ? 'text-primary' : 'text-mute'}`}
      aria-current={current ? 'page' : undefined}
      onClick={onClick}
    >
      {children}
    </button>
  )
}
