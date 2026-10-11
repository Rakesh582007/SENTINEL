import { useState } from 'react'
import { useLiveFeed } from './api/useLiveFeed.js'
import Splash from './components/Splash.jsx'
import TopBar from './components/TopBar.jsx'
import MapView from './components/map/MapView.jsx'
import { StateChip } from './components/ui.jsx'
import { CELL_STATES } from './lib/states.js'
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

function PictureNow() {
  const tick = useStore((s) => s.tick)
  const counts = tick?.stats?.cells || {}
  return (
    <div className="space-y-3 p-4">
      <h2 className="text-[17px] font-bold">Hexagons right now</h2>
      <ul className="space-y-1.5">
        {CELL_STATES.map((st) => (
          <li key={st} className="flex items-center justify-between">
            <StateChip state={st} />
            <span className="font-data text-[15px] tnum">{counts[st] || 0}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function App() {
  const [intro, setIntro] = useState(introWanted)
  const tab = useStore((s) => s.tab)
  useLiveFeed()

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
          <MapView />
        </section>
        {mapTab ? (
          <aside className="min-h-0 w-full overflow-y-auto border-sand-300 bg-sand-100 lg:w-[30%] lg:min-w-[350px] lg:max-w-[470px] lg:border-l">
            <PictureNow />
          </aside>
        ) : (
          <div className="grid flex-1 place-items-center text-ink-600">Ground Sentinel arrives in step 5.</div>
        )}
      </main>
      {intro ? <Splash onEnter={enter} /> : null}
    </div>
  )
}
