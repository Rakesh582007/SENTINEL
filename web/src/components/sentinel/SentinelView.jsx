import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client.js'
import { STANDALONE } from '../../config.js'
import { fmtLatLon } from '../../lib/geo.js'
import { MEDIUM_DB, STRONG_DB, satName, signalBand } from '../../lib/satellites.js'
import { SIM_SATS } from '../../lib/satellites.js'
import { sentinelOf } from '../../lib/states.js'
import { ago, istTime } from '../../lib/time.js'
import { useStore } from '../../store.js'
import { Button, Fact, InjectedBadge, useNow } from '../ui.jsx'
import LineChart from './LineChart.jsx'
import { baseValues, JAM_HOLD_S, JAM_SNR_DB, SIM_BASELINE, SIM_ID, useSim } from './simStore.js'

const WINDOW_S = 300

function useHistory(device) {
  const [rows, setRows] = useState([])
  useEffect(() => {
    if (!device) return undefined
    let alive = true
    const load = () =>
      api
        .sentinelHistory(device, WINDOW_S / 60)
        .then((r) => alive && Array.isArray(r) && setRows(r))
        .catch(() => {})
    load()
    const t = window.setInterval(load, 2000)
    return () => {
      alive = false
      window.clearInterval(t)
    }
  }, [device])
  return rows
}

/** Status changes, kept for as long as the tab is open. */
function useEventLog(device, rows) {
  const log = useRef({ device: null, last: null, events: [] })
  if (log.current.device !== device) log.current = { device, last: null, events: [] }
  const L = log.current
  for (const p of rows) {
    if (L.last && p.recv_ts <= L.last.recv_ts) continue
    if (!L.last || p.server_status !== L.last.server_status) {
      L.events.unshift({ ts: p.recv_ts, status: p.server_status, reason: p.server_reason })
      L.events = L.events.slice(0, 40)
    }
    L.last = p
  }
  return L.events
}

const MAX_DB = 55

/** One row per satellite: name, bar (or slider in Attack mode), value and the word Strong / Medium / Weak. */
function SatelliteList({ entries, baseline, onChange }) {
  if (!entries.length) return <p className="text-[14px] text-ink-600">The box sent no per-satellite values.</p>
  return (
    <ul className="space-y-1.5" aria-label="Signal per satellite">
      {entries.map((e, i) => {
        const band = signalBand(e.v)
        const pct = Math.min(100, Math.max(0, (e.v / MAX_DB) * 100))
        return (
          <li key={e.key} className="grid grid-cols-[6.6rem_1fr_8.2rem] items-center gap-2">
            <span className="truncate text-[13px] font-semibold text-ink-900" title={e.name}>
              {e.name}
            </span>
            <span className="relative flex h-5 items-center">
              {onChange ? (
                <input
                  type="range"
                  className="sat-slider w-full"
                  min={0}
                  max={MAX_DB}
                  step={1}
                  value={Math.round(e.v)}
                  aria-label={`${e.name} signal in dB-Hz`}
                  style={{ '--fill': band.color, '--pct': `${pct}%` }}
                  onChange={(ev) => onChange(i, Number(ev.target.value))}
                />
              ) : (
                <span className="relative block h-3.5 w-full rounded-sm bg-sand-200">
                  <span className="absolute inset-y-0 left-0 rounded-r-[4px]" style={{ width: `${Math.max(2, pct)}%`, background: band.color }} />
                </span>
              )}
              {baseline ? (
                <span
                  className="pointer-events-none absolute inset-y-0 w-px bg-ink-700"
                  style={{ left: `${(baseline / MAX_DB) * 100}%` }}
                  title={`normal level ${baseline.toFixed(1)} dB-Hz`}
                />
              ) : null}
            </span>
            <span className="text-right text-[12.5px] text-ink-900">
              <span className="font-data tnum">{Math.round(e.v)} dB-Hz</span>{' '}
              <span className="font-semibold" style={{ color: band.ink }}>
                {band.label}
              </span>
            </span>
          </li>
        )
      })}
    </ul>
  )
}

function SignalLegend() {
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-ink-700">
      {[
        ['strong', `${STRONG_DB} dB-Hz or more`],
        ['medium', `${MEDIUM_DB} to ${STRONG_DB}`],
        ['weak', `under ${MEDIUM_DB}`],
      ].map(([k, range]) => {
        const b = signalBand(k === 'strong' ? STRONG_DB : k === 'medium' ? MEDIUM_DB : 0)
        return (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: b.color }} aria-hidden="true" />
            <span className="font-semibold" style={{ color: b.ink }}>
              {b.label}
            </span>
            {range}
          </span>
        )
      })}
      <span className="inline-flex items-center gap-1.5">
        <span className="inline-block h-3 w-px bg-ink-700" aria-hidden="true" /> normal level
      </span>
    </p>
  )
}

function realEntries(box) {
  const list = Array.isArray(box.snr_list) ? box.snr_list : []
  const ids = Array.isArray(box.sat_ids) ? box.sat_ids : []
  return list.map((v, i) => ({ key: i, v: typeof v === 'number' ? v : 0, name: satName(ids[i] ?? null, i) }))
}

function SimulateFoil() {
  // Standalone build only: the in-browser backend fakes the box.
  const [busy, setBusy] = useState(false)
  if (!STANDALONE) return null
  const press = async () => {
    setBusy(true)
    try {
      await window.__standalone?.coverAntenna?.(25)
    } finally {
      window.setTimeout(() => setBusy(false), 25000)
    }
  }
  return (
    <div className="rounded-lg border border-dashed border-air-500 bg-air-50 p-3">
      <p className="text-[13.5px] leading-snug text-ink-700">
        Standalone build: this box is simulated in your browser. On the day, the ESP32 sends real packets and a teammate covers the antenna with foil.
      </p>
      <button
        type="button"
        onClick={press}
        disabled={busy}
        className="mt-2 rounded-md bg-air-600 px-3 py-1.5 text-[14px] font-semibold text-white hover:bg-air-700 disabled:opacity-60"
      >
        {busy ? 'Antenna covered for 25 s…' : 'Cover the antenna (simulated)'}
      </button>
    </div>
  )
}

function ModeToggle({ mode, setMode }) {
  return (
    <div className="inline-flex rounded-lg border border-air-300 bg-air-50 p-0.5" role="group" aria-label="Ground sentinel source">
      {[
        ['live', 'Live', 'real box, via the backend'],
        ['attack', 'Attack', 'set the dB by hand'],
      ].map(([id, label, sub]) => {
        const active = mode === id
        return (
          <button
            key={id}
            type="button"
            aria-pressed={active}
            onClick={() => setMode(id)}
            className={`rounded-md px-4 py-1.5 text-left leading-tight transition-colors ${
              active ? (id === 'attack' ? 'bg-[#F26B1D] text-white' : 'bg-air-600 text-white') : 'text-ink-700 hover:bg-air-100'
            }`}
          >
            <span className="block text-[15px] font-bold">{label}</span>
            <span className={`block text-[11.5px] ${active ? 'text-white/90' : 'text-ink-600'}`}>{sub}</span>
          </button>
        )
      })}
    </div>
  )
}

function BackendLine({ box }) {
  const connection = useStore((s) => s.connection)
  const up = connection.state === 'open'
  let text
  let tone
  if (!up) {
    text = 'Backend not reachable. Showing the last values; this page reconnects by itself.'
    tone = '#E5484D'
  } else if (!box) {
    text = 'Connected to the backend. Waiting for the box to post its first packet.'
    tone = '#E8A33C'
  } else if (box.server_status === 'OFFLINE') {
    text = `Connected to the backend. The box has been silent for ${ago(box.age_s).replace(' ago', '')}.`
    tone = '#E8A33C'
  } else {
    text = `Connected to the backend. Reading real packets from ${box.id}.`
    tone = '#2EAF6E'
  }
  return (
    <p className="flex items-center gap-2 text-[13.5px] text-ink-700" role="status">
      <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: tone }} aria-hidden="true" />
      {text}
    </p>
  )
}

function AttackControls() {
  const values = useSim((s) => s.values)
  const setDrop = useSim((s) => s.setDrop)
  const reset = useSim((s) => s.reset)
  const base = baseValues()
  const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length
  const drop = Math.min(30, Math.max(0, Math.round(mean(base) - mean(values))))
  return (
    <section className="space-y-3 rounded-lg border-2 border-[#F26B1D] bg-[#FFF4EB] p-3.5" aria-labelledby="atk-title">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="atk-title" className="text-[16px] font-bold text-ink-900">
          Manual signal test
        </h2>
        <InjectedBadge />
      </div>
      <p className="text-[13.5px] leading-snug text-ink-700">
        Drag any satellite&apos;s signal below, or lower them all at once. The status uses the server&apos;s rule: an average signal below {JAM_SNR_DB} dB-Hz reads as
        jamming (normal here is {SIM_BASELINE.toFixed(1)}); it must stay there for {JAM_HOLD_S} seconds; anything above is normal, even without a fix. Nothing is sent to the real box or the backend.
      </p>
      <div>
        <div className="flex items-baseline justify-between">
          <label htmlFor="atk-drop" className="text-[14px] font-semibold text-ink-900">
            Lower every satellite by
          </label>
          <span className="font-data text-[14px] font-bold text-ink-900 tnum">{drop} dB</span>
        </div>
        <input id="atk-drop" type="range" className="signal w-full" min={0} max={30} step={1} value={drop} onChange={(e) => setDrop(Number(e.target.value))} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => setDrop(0)}>
          Healthy
        </Button>
        <Button size="sm" onClick={() => setDrop(10)}>
          Weaker by 10 dB (still normal)
        </Button>
        <Button size="sm" onClick={() => setDrop(20)}>
          Jam: 20 dB down
        </Button>
        <Button size="sm" variant="ghost" onClick={reset}>
          Reset
        </Button>
      </div>
    </section>
  )
}

function Body({ box, rows, events, simulated, entries, onSatChange, controls, notice }) {
  useNow(1000)
  const nowS = Date.now() / 1000
  const s = sentinelOf(box.server_status)
  const alarm = box.server_status === 'JAMMING' || box.server_status === 'SPOOF'
  const baseline = box.baseline_snr
  const snrPoints = rows.map((p) => ({ t: p.recv_ts, v: typeof p.avg_snr === 'number' ? p.avg_snr : null }))
  const satPoints = rows.map((p) => ({ t: p.recv_ts, v: typeof p.sats_used === 'number' ? p.sats_used : null }))
  const refs = [
    ...(baseline ? [{ label: `normal ${baseline.toFixed(1)}`, value: baseline, color: '#4B5E78' }] : []),
    { label: `jamming < ${JAM_SNR_DB}`, value: JAM_SNR_DB, color: '#E5484D', ink: '#8F1F23' },
  ]

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(320px,2fr)_3fr]">
      <div className="min-w-0 space-y-4">
        <section className="rounded-xl border-2 p-5" style={{ borderColor: s.color, background: `${s.color}14` }} aria-live="polite">
          <p className="text-[14px] font-semibold text-ink-700">{simulated ? 'Status from the server rules, on your values' : 'Status checked by the server'}</p>
          <p className="mt-1 font-data text-[44px] font-bold leading-none tracking-[0.04em]" style={{ color: s.ink }}>
            {s.label.toUpperCase()}
          </p>
          <p className="mt-2 text-[16px] leading-snug text-ink-900">{box.server_reason ? `${box.server_reason[0].toUpperCase()}${box.server_reason.slice(1)}.` : s.words}</p>
          {simulated ? (
            <div className="mt-3">
              <InjectedBadge />
            </div>
          ) : alarm ? (
            <p className="mt-3 inline-block rounded-md bg-ink-900 px-2.5 py-1 text-[13px] font-bold tracking-[0.03em] text-white">SIGNAL TEST (antenna covered)</p>
          ) : null}
          {!simulated && box.status && box.status !== box.server_status && box.server_status !== 'OFFLINE' ? (
            <p className="mt-2 text-[13px] text-ink-600">The box itself says {box.status}; the dashboard trusts the server&apos;s own check.</p>
          ) : null}
        </section>

        {!simulated && !box.rule && box.server_status !== 'OFFLINE' ? (
          <p role="alert" className="rounded-lg border-2 border-[#E8A33C] bg-[#FFF6E5] px-3 py-2 text-[13.5px] font-semibold leading-snug text-ink-900">
            The backend is running an old copy of the Sentinel rules, so this status can be wrong. Stop uvicorn and start it again (no --reload), then refresh this page.
          </p>
        ) : null}

        {controls}

        <dl className="rounded-lg border border-sand-400 bg-sand-50 px-3 py-1">
          {simulated ? null : <Fact label="Last packet">{ago(box.age_s)}</Fact>}
          <Fact label="Satellite fix">{box.fix ? 'Yes' : 'No'}</Fact>
          <Fact label="Satellites used / in view" mono>
            {box.sats_used ?? '–'} / {box.sats_in_view ?? '–'}
          </Fact>
          <Fact label="Average signal" mono>
            {typeof box.avg_snr === 'number' ? `${box.avg_snr.toFixed(1)} dB-Hz` : '–'}
          </Fact>
          <Fact label={simulated ? 'Normal level' : 'Baseline'} mono>
            {baseline ? `${baseline.toFixed(1)} dB-Hz` : 'learning (first 2 min with a fix)'}
          </Fact>
          {simulated ? null : (
            <Fact label="Position" mono>
              {fmtLatLon(box.lat, box.lon)}
            </Fact>
          )}
        </dl>

        <p className="text-[14px] leading-relaxed text-ink-700">
          {simulated
            ? 'This is a stand-in for the real box, so the rules can be shown without hardware. Switch to Live to see the real one.'
            : `The box learns its normal satellite signal in its first two minutes with a fix. An average signal below ${JAM_SNR_DB} dB-Hz for ${JAM_HOLD_S} seconds in a row reads as jamming (above it is normal, even if the fix drops); a fixed box that appears to move reads as spoofing. It shows the method on a table; at border airports it would cover the gaps where too few aircraft fly.`}
        </p>
        {notice}
      </div>

      <div className="min-w-0 space-y-6">
        <section aria-labelledby="bars-title" className="space-y-2">
          <h2 id="bars-title" className="text-[17px] font-bold text-ink-900">
            {onSatChange ? 'Signal per satellite (drag to change)' : 'Signal per satellite now'}
          </h2>
          <SignalLegend />
          <SatelliteList entries={entries} baseline={baseline} onChange={onSatChange} />
        </section>
        <section aria-labelledby="snr-title">
          <h2 id="snr-title" className="text-[17px] font-bold text-ink-900">
            Average satellite signal, last 5 minutes
          </h2>
          <p className="text-[13px] text-ink-600">C/N0 in dB-Hz. {simulated ? 'Dragging the sliders down shows as a cliff below the red line.' : 'Foil over the antenna shows as a cliff below the red line.'}</p>
          <LineChart points={snrPoints} now={nowS} windowS={WINDOW_S} unit="dB-Hz" refs={refs} label="Average satellite signal" />
        </section>
        <section aria-labelledby="sats-title">
          <h2 id="sats-title" className="text-[17px] font-bold text-ink-900">
            Satellites used in the fix
          </h2>
          <LineChart points={satPoints} now={nowS} windowS={WINDOW_S} yDomain={[0, 14]} step decimals={0} label="Satellites used" height={140} />
        </section>
        <section aria-labelledby="log-title" className="space-y-2">
          <h2 id="log-title" className="text-[17px] font-bold text-ink-900">
            Event log
          </h2>
          {events.length ? (
            <ul className="divide-y divide-sand-300 rounded-lg border border-sand-400 bg-sand-50">
              {events.map((e) => {
                const st = sentinelOf(e.status)
                const alarmEv = e.status === 'JAMMING' || e.status === 'SPOOF'
                return (
                  <li key={`${e.ts}-${e.status}`} className="flex flex-wrap items-baseline gap-x-3 px-3 py-1.5 text-[14px]">
                    <span className="font-data text-[13px] text-ink-700 tnum">{istTime(e.ts)}</span>
                    <span className="font-semibold" style={{ color: st.ink }}>
                      {st.label}
                    </span>
                    <span className="text-ink-700">
                      {e.reason || st.words}
                      {alarmEv ? (simulated ? ' (injected test)' : ' (signal test)') : ''}
                    </span>
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="text-[14px] text-ink-600">No status changes yet.</p>
          )}
        </section>
      </div>
    </div>
  )
}

function LiveSentinel() {
  const tick = useStore((s) => s.tick)
  const boxes = tick?.sentinel || []
  const [chosen, setChosen] = useState(null)
  const box = boxes.find((b) => b.id === chosen) || boxes[0]
  const rows = useHistory(box?.id)
  const events = useEventLog(box?.id, rows)

  if (!box) {
    return (
      <div className="max-w-2xl space-y-4">
        <BackendLine box={null} />
        <p className="text-[16px] leading-relaxed text-ink-900">No Ground Sentinel has reported yet.</p>
        <ol className="list-decimal space-y-1.5 pl-5 text-[15px] leading-relaxed text-ink-700">
          <li>Join the ESP32 and this laptop to the same phone hotspot.</li>
          <li>
            Start the backend with <code className="rounded bg-sand-200 px-1 font-data text-[13px]">--host 0.0.0.0</code> so the box can reach it.
          </li>
          <li>
            The firmware posts JSON to <code className="rounded bg-sand-200 px-1 font-data text-[13px]">http://&lt;laptop-ip&gt;:8000/api/sentinel</code> every 2 s. It shows up here within
            seconds.
          </li>
          <li>Indoors with no sky view it says Searching. That is not an alarm.</li>
        </ol>
        <p className="text-[14px] text-ink-600">Want to try the screen without the box? Switch to Attack above.</p>
        <SimulateFoil />
      </div>
    )
  }

  const named = Array.isArray(box.sat_ids) && box.sat_ids.length > 0
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <BackendLine box={box} />
        {boxes.length > 1 ? (
          <select className="rounded-md border border-sand-400 bg-sand-50 px-2 py-1 text-[14px]" value={box.id} onChange={(e) => setChosen(e.target.value)} aria-label="Device">
            {boxes.map((b) => (
              <option key={b.id} value={b.id}>
                {b.id}
              </option>
            ))}
          </select>
        ) : (
          <span className="font-data text-[13px] text-ink-600">{box.id}</span>
        )}
      </div>
      <Body
        box={box}
        rows={rows}
        events={events}
        simulated={false}
        entries={realEntries(box)}
        notice={
          <>
            {named || !box.snr_list?.length ? null : (
              <p className="text-[13px] leading-snug text-ink-600">
                Satellites are numbered in the order the box reports them. To show names like GPS G12, the firmware adds <code className="font-data">sat_ids</code> (the satellite numbers from the
                receiver) next to <code className="font-data">snr_list</code>.
              </p>
            )}
            <SimulateFoil />
          </>
        }
      />
    </div>
  )
}

function AttackSentinel() {
  const values = useSim((s) => s.values)
  const history = useSim((s) => s.history)
  const setValue = useSim((s) => s.setValue)
  const tick = useSim((s) => s.tick)

  useEffect(() => {
    tick(Date.now() / 1000)
    const t = window.setInterval(() => tick(Date.now() / 1000), 1000)
    return () => window.clearInterval(t)
  }, [tick])

  const rows = history.filter((r) => r.recv_ts >= Date.now() / 1000 - WINDOW_S - 5)
  const events = useEventLog(SIM_ID, history)
  const last = history[history.length - 1]
  if (!last) return null
  const box = {
    id: SIM_ID,
    server_status: last.server_status,
    server_reason: last.server_reason,
    status: last.server_status,
    baseline_snr: SIM_BASELINE,
    age_s: 0,
    fix: last.fix,
    sats_used: last.sats_used,
    sats_in_view: SIM_SATS.length,
    avg_snr: last.avg_snr,
  }
  const entries = SIM_SATS.map((sat, i) => ({ key: sat.id, name: sat.name, v: values[i] }))
  return <Body box={box} rows={rows} events={events} simulated entries={entries} onSatChange={setValue} controls={<AttackControls />} />
}

export default function SentinelView() {
  const [mode, setMode] = useState('live')
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1400px] space-y-4 p-4 lg:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-[22px] font-bold text-ink-900">Ground sentinel</h1>
          <ModeToggle mode={mode} setMode={setMode} />
        </div>
        {mode === 'live' ? <LiveSentinel /> : <AttackSentinel />}
      </div>
    </div>
  )
}
