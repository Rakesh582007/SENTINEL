import { useState } from 'react'
import Splash from './components/Splash.jsx'
import TopBar from './components/TopBar.jsx'
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

  const enter = () => {
    try {
      window.sessionStorage.setItem(INTRO_KEY, '1')
    } catch {
      /* storage blocked: the intro simply shows again next time */
    }
    setIntro(false)
  }

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <main className="relative min-h-0 flex-1" id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>
        <div className="grid h-full place-items-center text-ink-600">Map and panels arrive in the next step.</div>
      </main>
      {intro ? <Splash onEnter={enter} /> : null}
    </div>
  )
}
