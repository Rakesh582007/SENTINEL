import { useEffect, useState } from 'react'
import { api, errorText } from '../../api/client.js'
import { STANDALONE } from '../../config.js'
import { istDay, istHM, istTime } from '../../lib/time.js'
import { useStore } from '../../store.js'
import { useDataElapsed } from './useDataClock.js'

const SPEEDS = [1, 2, 5, 10, 20]

function PlayIcon({ paused }) {
  return paused ? (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <path d="M3 1.5v11l9-5.5z" fill="currentColor" />
    </svg>
  ) : (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
      <path d="M3 1.5h3v11H3zM8 1.5h3v11H8z" fill="currentColor" />
    </svg>
  )
}

function Replay({ r }) {
  const toast = useStore((s) => s.toast)
  const elapsed = useDataElapsed()
  const [drag, setDrag] = useState(null) // scrubber value while the pointer is down
  const [busy, setBusy] = useState(false)
  const now = Math.min(r.t_end, (r.ts || r.t_start) + elapsed)
  const span = Math.max(1, r.t_end - r.t_start)

  const call = async (fn, ok) => {
    setBusy(true)
    try {
      await fn()
      if (ok) toast(ok, 'ok')
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  const seek = (ts) => call(() => api.seek(ts), `Jumped to ${istHM(ts)} IST. Incidents restart from here; simulated attacks stay on.`)

  if (r.error) {
    return <p className="text-[13.5px] font-semibold text-[#8F1F23]">Replay has no data: {r.error}</p>
  }

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <button
        type="button"
        onClick={() => call(() => (r.paused ? api.play() : api.pause()))}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-md bg-air-600 px-3 py-1.5 text-[13.5px] font-semibold text-white hover:bg-air-700 disabled:opacity-60"
        aria-label={r.paused ? 'Play replay' : 'Pause replay'}
      >
        <PlayIcon paused={r.paused} />
        {r.paused ? 'Play' : 'Pause'}
      </button>
      <div className="flex overflow-hidden rounded-md border border-sand-400" role="group" aria-label="Replay speed">
        {SPEEDS.map((sp) => (
          <button
            key={sp}
            type="button"
            aria-pressed={r.speed === sp}
            onClick={() => r.speed !== sp && call(() => api.speed(sp))}
            className={`px-2 py-1 font-data text-[12.5px] ${r.speed === sp ? 'bg-air-600 text-white' : 'bg-sand-50 text-ink-700 hover:bg-air-50'}`}
          >
            {sp}×
          </button>
        ))}
      </div>
      <div className="flex min-w-[220px] flex-1 items-center gap-2">
        <span className="font-data text-[12px] text-ink-600 tnum">{istHM(r.t_start)}</span>
        <input
          type="range"
          aria-label="Replay timeline"
          className="min-w-0 flex-1"
          min={Math.floor(r.t_start)}
          max={Math.ceil(r.t_end)}
          step={1}
          value={Math.round(drag ?? now)}
          onChange={(e) => setDrag(Number(e.target.value))}
          onPointerUp={() => {
            if (drag != null) seek(drag)
            setDrag(null)
          }}
          onKeyUp={(e) => {
            if (drag != null && ['ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageUp', 'PageDown'].includes(e.key)) {
              seek(drag)
              setDrag(null)
            }
          }}
        />
        <span className="font-data text-[12px] text-ink-600 tnum">{istHM(r.t_end)}</span>
      </div>
      <div className="text-[12.5px] leading-tight text-ink-700">
        <div>
          <span className="font-data text-[13px] text-ink-900 tnum">{istTime(drag ?? now)}</span> IST, {Math.round(((drag ?? now) - r.t_start) / span * 100)}%
        </div>
        <div className="text-ink-600">
          Recording {istDay(r.t_start)} {istHM(r.t_start)}–{istHM(r.t_end)} IST{r.sample ? ', bundled sample' : ''}
          {r.segments > 1 ? `, ${r.segments} stretches (gaps skipped)` : ''}
        </div>
      </div>
    </div>
  )
}

function Live() {
  const toast = useStore((s) => s.toast)
  const [regions, setRegions] = useState(null)
  const [health, setHealth] = useState(null)

  useEffect(() => {
    api.regions().then(setRegions).catch(() => setRegions(null))
  }, [])
  useEffect(() => {
    let alive = true
    const load = () =>
      api
        .health()
        .then((h) => alive && setHealth(h))
        .catch(() => {})
    load()
    const t = window.setInterval(load, 10000)
    return () => {
      alive = false
      window.clearInterval(t)
    }
  }, [])

  const choose = async (name) => {
    try {
      const r = await api.setRegion(name)
      setRegions((cur) => (cur ? { ...cur, current: r.current } : cur))
      toast(`Region ${name}: applies from the next polling sweep.`, 'ok')
    } catch (e) {
      toast(`Could not change region: ${errorText(e)}`, 'error')
    }
  }

  const stats = health?.source_stats || {}
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[13.5px] text-ink-700">
      <span className="font-semibold text-ink-900">Live data, polled from adsb.fi and adsb.lol</span>
      {regions ? (
        <label className="flex items-center gap-2">
          Region
          <select
            className="rounded-md border border-sand-400 bg-sand-50 px-2 py-1 text-[13.5px] text-ink-900"
            value={regions.current}
            onChange={(e) => choose(e.target.value)}
          >
            {Object.keys(regions.presets || {}).map((n) => (
              <option key={n} value={n}>
                {n.replace('_', ' ')}
              </option>
            ))}
            {regions.current === 'custom' ? <option value="custom">custom</option> : null}
          </select>
        </label>
      ) : null}
      <span className="flex flex-wrap gap-x-3">
        {Object.entries(stats).map(([src, s]) => (
          <span key={src}>
            {src}: <span className="font-data tnum">{s.ok}</span> ok, <span className="font-data tnum">{s.fail}</span> failed
            {s.last_error ? <span className="text-[#8F1F23]"> ({s.last_error})</span> : null}
          </span>
        ))}
      </span>
    </div>
  )
}

/** Bottom bar of the map: replay transport, or live source status. */
export default function ReplayControls() {
  const tick = useStore((s) => s.tick)
  if (!tick) return null
  return (
    <div className="pointer-events-auto rounded-lg border border-sand-400 bg-sand-50/95 px-3 py-2 shadow-float">
      {tick.mode === 'replay' && tick.replay ? <Replay r={tick.replay} /> : null}
      {tick.mode === 'live' ? (STANDALONE ? <p className="text-[13.5px] text-ink-700">Live polling needs the real backend. Switch back to Replay.</p> : <Live />) : null}
    </div>
  )
}
