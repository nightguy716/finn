import { useCallback, useEffect, useState } from 'react'
import { fetchAlertConfig, fetchFeed } from './api'
import { Briefing } from './components/Briefing'
import { Research } from './components/Research'
import { AlertSheet, SettingsSheet } from './components/Sheets'
import type { Alert, AlertConfig, Feed, LoadStatus } from './types'

type Tab = 'briefing' | 'research'

export default function App() {
  const [tab, setTab] = useState<Tab>('briefing')
  const [asOf, setAsOf] = useState('2026-11-06')
  const [hours, setHours] = useState(72)
  const [move, setMove] = useState(5)
  const [volume, setVolume] = useState(2.5)
  const [defaults, setDefaults] = useState<AlertConfig | null>(null)
  const [feed, setFeed] = useState<Feed | null>(null)
  const [status, setStatus] = useState<LoadStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [alert, setAlert] = useState<Alert | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)

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
    fetchFeed({ asOf, hours, movePct: move, volumeN: volume }, ctrl.signal)
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
  }, [asOf, hours, move, volume, attempt])

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

  return (
    <div className="flex h-dvh justify-center bg-desk text-ink">
      <div className="relative flex h-dvh w-full max-w-[390px] flex-col overflow-hidden bg-paper">
        <main className="min-h-0 flex-1 overflow-y-auto">
          {tab === 'briefing' ? (
            <Briefing
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
              onHours={setHours}
              onOpenSettings={() => setSettingsOpen(true)}
              onOpenAlert={setAlert}
            />
          ) : (
            <Research />
          )}
        </main>
        <nav className="flex shrink-0 border-t border-line bg-paper pb-[env(safe-area-inset-bottom)]" aria-label="Primary">
          <TabButton current={tab === 'briefing'} onClick={() => setTab('briefing')}>
            Briefing
          </TabButton>
          <TabButton current={tab === 'research'} onClick={() => setTab('research')}>
            Research
          </TabButton>
        </nav>
        <AlertSheet alert={alert} cards={feed?.cards ?? []} onClose={closeAlert} onJump={jump} />
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
      className={`h-12 flex-1 text-[13px] ${current ? 'text-accent' : 'text-mute'}`}
      aria-current={current ? 'page' : undefined}
      onClick={onClick}
    >
      {children}
    </button>
  )
}
