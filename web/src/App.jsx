import { useEffect, useState } from 'react'
import { api } from './api/client.js'
import { useLiveFeed } from './api/useLiveFeed.js'
import Splash from './components/Splash.jsx'
import TopBar from './components/TopBar.jsx'
import IncidentCircles from './components/map/IncidentCircles.jsx'
import MapView from './components/map/MapView.jsx'
import WarningPaths from './components/map/WarningPaths.jsx'
import AirspacePanel from './components/panels/AirspacePanel.jsx'
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
    setIntro(false)
  }

  const mapTab = tab === 'airspace' || tab === 'simulator'

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <main className="relative flex min-h-0 flex-1 flex-col lg:flex-row" id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        <section className="relative h-[58vh] min-h-[320px] lg:h-auto lg:min-h-0 lg:flex-1" aria-label="Map" hidden={!mapTab}>
          <MapView
            overlays={
              <>
                <IncidentCircles />
                <WarningPaths />
              </>
            }
          />
        </section>
        {mapTab ? (
          <aside className="min-h-0 w-full overflow-y-auto border-sand-300 bg-sand-100 lg:w-[30%] lg:min-w-[350px] lg:max-w-[470px] lg:border-l">
            {tab === 'airspace' ? <AirspacePanel /> : <div className="p-4 text-ink-600">Attack simulator arrives in step 3.</div>}
          </aside>
        ) : (
          <div className="grid flex-1 place-items-center text-ink-600">Ground Sentinel arrives in step 5.</div>
        )}
      </main>
      {intro ? <Splash onEnter={enter} /> : null}
    </div>
  )
}
