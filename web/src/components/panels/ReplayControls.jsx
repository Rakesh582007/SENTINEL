import { useEffect, useState } from 'react'
import { api, errorText } from '../../api/client.js'
import { STANDALONE } from '../../config.js'
import { incidentNumber, replayIncident } from '../../lib/incidents.js'
import { istDay, istHM, istTime } from '../../lib/time.js'
import { useDerived, useStore } from '../../store.js'
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

function Replay({ r: tickReplay }) {
  const toast = useStore((s) => s.toast)
  const override = useStore((s) => s.replayOverride)
  const setReplayOverride = useStore((s) => s.setReplayOverride)
  const r = { ...tickReplay, ...(override || {}) }
  const elapsed = useDataElapsed()
  const [drag, setDrag] = useState(null) // scrubber value while the pointer is down
  const [busy, setBusy] = useState(false)
  const now = Math.min(r.t_end, (r.ts || r.t_start) + elapsed)
  const span = Math.max(1, r.t_end - r.t_start)
  const d = useDerived()
  const marks = d.incidents.filter((i) => i.opened_ts >= r.t_start && i.opened_ts <= r.t_end)

  const call = async (fn, ok) => {
    setBusy(true)
    try {
      await fn()
      if (ok) toast(ok, 'ok')
    } catch (e) {
      setReplayOverride(null)
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
        onClick={() => {
          const paused = !r.paused
          setReplayOverride({ paused })
          call(() => (paused ? api.pause() : api.play()))
        }}
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
            onClick={() => {
              if (r.speed === sp) return
              setReplayOverride({ speed: sp })
              call(() => api.speed(sp))
            }}
            className={`px-2 py-1 font-data text-[12.5px] ${r.speed === sp ? 'bg-air-600 text-white' : 'bg-sand-50 text-ink-700 hover:bg-air-50'}`}
          >
            {sp}×
          </button>
        ))}
      </div>
      <div className="flex min-w-[220px] flex-1 items-center gap-2">
        <span className="font-data text-[12px] text-ink-600 tnum">{istHM(r.t_start)}</span>
        <div className="relative min-w-0 flex-1">
        {/* Incident markers: where each incident started in the recording. Click = replay it. */}
        <div className="pointer-events-none absolute inset-x-[7px] -top-[13px] h-3">
          {marks.map((i) => (
            <button
              key={i.id}
              type="button"
              title={`Incident #${incidentNumber(i)} (${i.kind}) started ${istTime(i.opened_ts)} IST. Click to replay.`}
              aria-label={`Replay incident ${incidentNumber(i)}`}
              onClick={() => replayIncident(i, d.cellsById)}
              className="pointer-events-auto absolute h-3 w-3 -translate-x-1/2 rounded-full border-2 border-sand-50"
              style={{ left: `${((i.opened_ts - r.t_start) / span) * 100}%`, background: i.kind === 'jamming' ? '#E5484D' : '#9B5DE5' }}
            />
          ))}
        </div>
        <input
          type="range"
          aria-label="Replay timeline"
          className="w-full"
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
        </div>
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

/** Live / Replay switch (Live airspace). The backend runs one mode for the whole app, so
 *  switching also clears the Attack Simulator's attacks and every incident list. */
function ModeSwitch({ mode }) {
  const toast = useStore((s) => s.toast)
  const setReplayFocus = useStore((s) => s.setReplayFocus)
  const attacks = useStore((s) => (s.tick?.attacks || []).filter((a) => a.live).length)
  const [busy, setBusy] = useState(false)
  const choose = async (next) => {
    if (next === mode || busy) return
    if (attacks && !window.confirm(`Switching to ${next} removes the ${attacks} running test ${attacks === 1 ? 'attack' : 'attacks'} and clears the incident lists. Continue?`)) return
    setBusy(true)
    try {
      await api.setMode(next)
      setReplayFocus(null)
      toast(next === 'live' ? 'Live: polling adsb.fi and adsb.lol now. Aircraft appear within about 10 s.' : 'Replay: playing the recorded traffic.', 'ok')
    } catch (e) {
      toast(`Could not switch: ${errorText(e)}`, 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex items-center gap-2">
      <div className="flex overflow-hidden rounded-md border border-sand-400 text-[13px] font-semibold" role="group" aria-label="Data source">
        {[
          ['live', 'Live now'],
          ['replay', 'Replay recording'],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={mode === id}
            disabled={busy || (STANDALONE && id === 'live')}
            onClick={() => choose(id)}
            className={`flex items-center gap-1.5 px-2.5 py-1 disabled:opacity-60 ${mode === id ? 'bg-air-600 text-white' : 'bg-sand-50 text-ink-700 hover:bg-air-50'}`}
            title={STANDALONE && id === 'live' ? 'Live polling needs the real backend' : undefined}
          >
            {id === 'live' ? <span className={`h-2 w-2 rounded-full ${mode === 'live' ? 'bg-[#7CF0A8]' : 'bg-[#2EAF6E]'}`} aria-hidden="true" /> : null}
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}

/** Bottom bar of the map: Live/Replay switch (Live airspace), then replay transport or live source status. */
export default function ReplayControls() {
  const tick = useStore((s) => s.tick)
  const tab = useStore((s) => s.tab)
  if (!tick) return null
  return (
    <div className="pointer-events-auto flex flex-col gap-2 rounded-lg border border-sand-400 bg-sand-50/95 px-3 py-2 shadow-float lg:flex-row lg:items-center lg:gap-4">
      {tab === 'airspace' ? <ModeSwitch mode={tick.mode} /> : null}
      <div className="min-w-0 flex-1">
      {tick.mode === 'replay' && tick.replay ? <Replay r={tick.replay} /> : null}
      {tick.mode === 'live' ? (STANDALONE ? <p className="text-[13.5px] text-ink-700">Live polling needs the real backend. Switch back to Replay.</p> : <Live />) : null}
      </div>
    </div>
  )
}
