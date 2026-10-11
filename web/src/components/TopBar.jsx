import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client.js'
import { STALE_AFTER_S } from '../config.js'
import { sentinelOf } from '../lib/states.js'
import { istTime, istDay } from '../lib/time.js'
import { useDerived, useStore } from '../store.js'
import { useNow } from './ui.jsx'

const TABS = [
  { id: 'airspace', label: 'Live airspace' },
  { id: 'simulator', label: 'Attack simulator' },
  { id: 'sentinel', label: 'Ground sentinel' },
]

function TabHint({ id }) {
  const tick = useStore((s) => s.tick)
  const d = useDerived()
  if (!tick) return null
  if (id === 'airspace') {
    const n = (tick.stats?.cells?.jammed || 0) + (tick.stats?.cells?.spoofing || 0)
    if (!n) return null
    return (
      <span className="ml-2 rounded bg-[#E5484D] px-1.5 text-[12px] font-bold leading-[1.5] text-white">
        {n} {n === 1 ? 'alarm' : 'alarms'}
      </span>
    )
  }
  if (id === 'simulator') {
    const n = d.attacks.filter((a) => a.live).length
    if (!n) return null
    return <span className="ml-2 rounded bg-signal-500 px-1.5 text-[12px] font-bold leading-[1.5] text-signal-900">{n} live</span>
  }
  const box = tick.sentinel?.[0]
  if (!box) return null
  const s = sentinelOf(box.server_status)
  return (
    <span className="ml-2 inline-flex items-center gap-1 text-[12.5px] font-semibold" style={{ color: s.ink }}>
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} aria-hidden="true" />
      {s.label}
    </span>
  )
}

function ModeSwitch() {
  const tick = useStore((s) => s.tick)
  const toast = useStore((s) => s.toast)
  const [asking, setAsking] = useState(null) // target mode awaiting confirmation
  const [busy, setBusy] = useState(false)
  const boxRef = useRef(null)
  const mode = tick?.mode

  useEffect(() => {
    if (!asking) return
    const onDown = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) setAsking(null)
    }
    const onKey = (e) => e.key === 'Escape' && setAsking(null)
    window.addEventListener('pointerdown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [asking])

  const switchTo = async (target) => {
    setBusy(true)
    try {
      await api.setMode(target)
      toast(target === 'live' ? 'Switched to live data. Attacks and incidents were cleared.' : 'Switched to replay. Attacks and incidents were cleared.', 'ok')
    } catch (e) {
      toast(`Could not switch mode: ${errorText(e)}`, 'error')
    } finally {
      setBusy(false)
      setAsking(null)
    }
  }

  return (
    <div className="relative" ref={boxRef}>
      <div className="flex rounded-md border border-air-300 bg-air-50 p-0.5" role="group" aria-label="Data source">
        {['replay', 'live'].map((m) => {
          const active = mode === m
          return (
            <button
              key={m}
              type="button"
              aria-pressed={active}
              disabled={!tick || busy}
              onClick={() => !active && setAsking(m)}
              className={`rounded px-2.5 py-0.5 text-[13px] font-semibold transition-colors ${
                active ? 'bg-air-600 text-white' : 'text-ink-700 hover:bg-air-100'
              } disabled:opacity-60`}
            >
              {m === 'replay' ? 'Replay' : 'Live'}
            </button>
          )
        })}
      </div>
      {asking ? (
        <div className="absolute right-0 top-full z-[1200] mt-2 w-72 rounded-lg border border-sand-400 bg-sand-50 p-3 shadow-float" role="dialog" aria-label="Confirm mode switch">
          <p className="text-[14px] leading-snug text-ink-900">
            {asking === 'live'
              ? 'Switch to live data from adsb.fi and adsb.lol? This clears simulated attacks and incidents.'
              : 'Switch to the recorded replay? This clears simulated attacks and incidents.'}
          </p>
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" className="rounded-md px-3 py-1 text-[14px] font-semibold text-ink-700 hover:bg-air-50" onClick={() => setAsking(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="rounded-md bg-air-600 px-3 py-1 text-[14px] font-semibold text-white hover:bg-air-700 disabled:opacity-60"
              disabled={busy}
              onClick={() => switchTo(asking)}
            >
              {busy ? 'Switching…' : asking === 'live' ? 'Switch to live' : 'Switch to replay'}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function Connection() {
  const connection = useStore((s) => s.connection)
  const tickRecvAt = useStore((s) => s.tickRecvAt)
  const now = useNow(1000)
  let tone = '#2EAF6E'
  let text = 'Connected'
  if (connection.state === 'connecting') {
    tone = '#E8A33C'
    text = 'Connecting…'
  } else if (connection.state === 'reconnecting') {
    tone = '#E5484D'
    const s = connection.retryAt ? Math.max(0, Math.ceil((connection.retryAt - now) / 1000)) : 0
    text = s > 0 ? `Reconnecting in ${s} s` : 'Reconnecting…'
  } else if (tickRecvAt && (performance.now() - tickRecvAt) / 1000 > STALE_AFTER_S) {
    tone = '#E8A33C'
    text = `No data for ${Math.round((performance.now() - tickRecvAt) / 1000)} s`
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-700" role="status" aria-live="polite">
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: tone }} aria-hidden="true" />
      {text}
    </span>
  )
}

export default function TopBar() {
  const tab = useStore((s) => s.tab)
  const setTab = useStore((s) => s.setTab)
  const tick = useStore((s) => s.tick)
  const setEvaluationOpen = useStore((s) => s.setEvaluationOpen)

  const onTabKey = (e) => {
    const i = TABS.findIndex((t) => t.id === tab)
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const next = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length]
      setTab(next.id)
      document.getElementById(`tab-${next.id}`)?.focus()
    }
  }

  return (
    <header className="relative z-[1100] flex flex-wrap items-center gap-x-6 gap-y-1 border-b border-air-300 bg-air-100 px-4 py-1.5">
      <div className="flex items-baseline gap-2.5 py-1">
        <span className="font-data text-[19px] font-bold tracking-[0.18em] text-ink-900">SENTINEL</span>
        <span className="hidden text-[14px] text-ink-600 sm:inline">GPS Attack Watch</span>
      </div>

      <nav className="-mb-1.5 flex self-stretch" role="tablist" aria-label="Sections" onKeyDown={onTabKey}>
        {TABS.map((t) => {
          const active = t.id === tab
          return (
            <button
              key={t.id}
              id={`tab-${t.id}`}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls={`panel-${t.id}`}
              tabIndex={active ? 0 : -1}
              onClick={() => setTab(t.id)}
              className={`flex items-center border-b-[3px] px-3 pb-2 pt-2 text-[15px] font-semibold transition-colors ${
                active ? 'border-air-600 text-ink-900' : 'border-transparent text-ink-600 hover:text-ink-900'
              }`}
            >
              {t.label}
              <TabHint id={t.id} />
            </button>
          )
        })}
      </nav>

      <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1">
        <ModeSwitch />
        <div className="leading-tight" title={tick ? `${istDay(tick.ts)}, data time in IST` : undefined}>
          <div className="font-data text-[15px] text-ink-900 tnum">
            {istTime(tick?.ts)} <span className="text-[11px] text-ink-600">IST</span>
          </div>
          <div className="text-[11.5px] text-ink-600">{tick ? (tick.mode === 'replay' ? 'replay time' : 'live') : 'waiting for data'}</div>
        </div>
        <div className="leading-tight">
          <div className="font-data text-[15px] text-ink-900 tnum">{tick?.stats?.aircraft ?? '–'}</div>
          <div className="text-[11.5px] text-ink-600">aircraft</div>
        </div>
        <Connection />
        <button
          type="button"
          onClick={() => setEvaluationOpen(true)}
          className="rounded-md border border-air-600 px-3 py-1 text-[14px] font-semibold text-air-700 hover:bg-air-50"
        >
          Evaluation
        </button>
      </div>
    </header>
  )
}
