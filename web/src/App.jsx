import { useEffect, useState } from 'react'
import { api } from './api/client.js'
import { STANDALONE } from './config.js'
import { useLiveFeed } from './api/useLiveFeed.js'
import EvaluationModal from './components/EvaluationModal.jsx'
import HomeView from './components/HomeView.jsx'
import Splash from './components/Splash.jsx'
import Toasts from './components/Toasts.jsx'
import TopBar from './components/TopBar.jsx'
import AttackCircles from './components/map/AttackCircles.jsx'
import IncidentCircles from './components/map/IncidentCircles.jsx'
import JammerEditor from './components/map/JammerEditor.jsx'
import MapView from './components/map/MapView.jsx'
import WarningPaths from './components/map/WarningPaths.jsx'
import AirspacePanel from './components/panels/AirspacePanel.jsx'
import ReplayControls from './components/panels/ReplayControls.jsx'
import SentinelView from './components/sentinel/SentinelView.jsx'
import SimulatorPanel from './components/simulator/SimulatorPanel.jsx'
import { useStore } from './store.js'

const INTRO_KEY = 'sentinel:intro-seen'

function introWanted() {
  try {
    const params = new URLSearchParams(window.location.search)
    if (params.has('nointro')) return false
    if (params.has('intro')) return true
    return window.sessionStorage.getItem(INTRO_KEY) !== '1'
  } catch {
    return true
  }
}

export default function App() {
  const [intro, setIntro] = useState(introWanted)
  const tab = useStore((s) => s.tab)
  const connected = useStore((s) => s.connection.state === 'open')
  const setDetection = useStore((s) => s.setDetection)
  const setTab = useStore((s) => s.setTab)
  const clearSelection = useStore((s) => s.clearSelection)
  useLiveFeed()

  // Thresholds are shown in explanations ("3 needed"); refresh whenever the feed (re)connects.
  useEffect(() => {
    if (!connected) return
    api.detection().then(setDetection).catch(() => {})
  }, [connected, setDetection])

  const enter = () => {
    try {
      window.sessionStorage.setItem(INTRO_KEY, '1')
    } catch {
      /* storage blocked: the intro simply shows again next time */
    }
    setTab('home')
    setIntro(false)
  }

  // No accounts: "Log out" just closes the dashboard and shows the intro again.
  const logout = () => {
    try {
      window.sessionStorage.removeItem(INTRO_KEY)
    } catch {
      /* ignore */
    }
    clearSelection()
    useStore.getState().setEvaluationOpen(false)
    setTab('home')
    setIntro(true)
  }

  const mapTab = tab === 'airspace' || tab === 'simulator'

  return (
    <div className="flex min-h-full flex-col lg:h-full">
      {STANDALONE ? (
        <p className="bg-ink-900 px-4 py-1 text-[12.5px] leading-snug text-white" role="note">
          Standalone preview. The backend runs in your browser and replays the real 19-minute sample from 11 Oct with the same detection rules. The Ground Sentinel is simulated;
          PDF reports, live data and the summary need the real backend.
        </p>
      ) : null}
      <TopBar onLogout={logout} />
      <main className="relative flex min-h-0 flex-1 flex-col lg:flex-row" id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        <section className="relative lg:min-h-0 lg:flex-1" aria-label="Map" hidden={!mapTab}>
          <MapView
            bottom={<ReplayControls />}
            overlays={
              <>
                <IncidentCircles />
                <AttackCircles />
                <WarningPaths />
                <JammerEditor />
              </>
            }
          />
        </section>
        {tab === 'home' ? (
          <div className="min-h-0 flex-1">
            <HomeView />
          </div>
        ) : mapTab ? (
          <aside className="w-full border-t border-sand-300 bg-sand-100 lg:min-h-0 lg:w-[30%] lg:min-w-[350px] lg:max-w-[470px] lg:overflow-y-auto lg:border-l lg:border-t-0">
            {tab === 'airspace' ? <AirspacePanel /> : <SimulatorPanel />}
          </aside>
        ) : (
          <div className="min-h-0 flex-1">
            <SentinelView />
          </div>
        )}
      </main>
      <EvaluationModal />
      <Toasts />
      {intro ? <Splash onEnter={enter} /> : null}
    </div>
  )
}
