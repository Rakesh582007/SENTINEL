import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client.js'
import { STANDALONE } from '../../config.js'
import { fmtLatLon } from '../../lib/geo.js'
import { sentinelOf } from '../../lib/states.js'
import { ago, istTime } from '../../lib/time.js'
import { useStore } from '../../store.js'
import { Fact, useNow } from '../ui.jsx'
import LineChart from './LineChart.jsx'

const WINDOW_S = 300
const ALARM_DROP_DB = 10 // backend sentinel.SNR_DROP_DB

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

function SatelliteBars({ snr, baseline }) {
  const list = (snr || []).filter((v) => typeof v === 'number').slice().sort((a, b) => b - a)
  if (!list.length) return <p className="text-[14px] text-ink-600">The box sent no per-satellite values.</p>
  const max = Math.max(50, ...list)
  return (
    <ul className="space-y-1" aria-label="Signal per satellite">
      {list.map((v, i) => (
        <li key={i} className="grid grid-cols-[3.2rem_1fr_3.6rem] items-center gap-2">
          <span className="text-[12.5px] text-ink-600">Sat {i + 1}</span>
          <span className="relative h-3.5 rounded-sm bg-sand-200">
            <span className="absolute inset-y-0 left-0 rounded-r-[4px] bg-air-600" style={{ width: `${Math.max(2, (v / max) * 100)}%` }} />
            {baseline ? <span className="absolute inset-y-[-3px] w-px bg-ink-700" style={{ left: `${(baseline / max) * 100}%` }} title={`baseline ${baseline.toFixed(1)}`} /> : null}
          </span>
          <span className="text-right font-data text-[12.5px] text-ink-900 tnum">{v.toFixed(0)} dB-Hz</span>
        </li>
      ))}
    </ul>
  )
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

export default function SentinelView() {
  const tick = useStore((s) => s.tick)
  const boxes = tick?.sentinel || []
  const [chosen, setChosen] = useState(null)
  const box = boxes.find((b) => b.id === chosen) || boxes[0]
  const rows = useHistory(box?.id)
  const events = useEventLog(box?.id, rows)
  useNow(1000)
  const nowS = Date.now() / 1000

  if (!box) {
    return (
      <div className="mx-auto max-w-2xl space-y-4 p-6">
        <h1 className="text-[24px] font-bold text-ink-900">Ground sentinel</h1>
        <p className="text-[16px] leading-relaxed text-ink-900">No Ground Sentinel has reported yet.</p>
        <ol className="list-decimal space-y-1.5 pl-5 text-[15px] leading-relaxed text-ink-700">
          <li>Join the ESP32 and this laptop to the same phone hotspot.</li>
          <li>
            Start the backend with <code className="rounded bg-sand-200 px-1 font-data text-[13px]">--host 0.0.0.0</code> so the box can reach it.
          </li>
          <li>
            The firmware posts JSON to <code className="rounded bg-sand-200 px-1 font-data text-[13px]">http://&lt;laptop-ip&gt;:8000/api/sentinel</code> every 2 s. It shows up here within seconds.
          </li>
          <li>Indoors with no sky view it says Searching. That is not an alarm.</li>
        </ol>
        <SimulateFoil />
      </div>
    )
  }

  const s = sentinelOf(box.server_status)
  const alarm = box.server_status === 'JAMMING' || box.server_status === 'SPOOF'
  const baseline = box.baseline_snr
  const snrPoints = rows.map((p) => ({ t: p.recv_ts, v: typeof p.avg_snr === 'number' ? p.avg_snr : null }))
  const satPoints = rows.map((p) => ({ t: p.recv_ts, v: typeof p.sats_used === 'number' ? p.sats_used : null }))
  const refs = baseline
    ? [
        { label: `baseline ${baseline.toFixed(1)}`, value: baseline, color: '#4B5E78' },
        { label: `alarm < ${(baseline - ALARM_DROP_DB).toFixed(1)}`, value: baseline - ALARM_DROP_DB, color: '#E5484D', ink: '#8F1F23' },
      ]
    : []

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto grid max-w-[1400px] gap-6 p-4 lg:grid-cols-[minmax(320px,2fr)_3fr] lg:p-6">
        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h1 className="text-[22px] font-bold text-ink-900">Ground sentinel</h1>
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

          <section className="rounded-xl border-2 p-5" style={{ borderColor: s.color, background: `${s.color}14` }} aria-live="polite">
            <p className="text-[14px] font-semibold text-ink-700">Status checked by the server</p>
            <p className="mt-1 font-data text-[44px] font-bold leading-none tracking-[0.04em]" style={{ color: s.ink }}>
              {s.label.toUpperCase()}
            </p>
            <p className="mt-2 text-[16px] leading-snug text-ink-900">{box.server_reason ? `${box.server_reason[0].toUpperCase()}${box.server_reason.slice(1)}.` : s.words}</p>
            {alarm ? (
              <p className="mt-3 inline-block rounded-md bg-ink-900 px-2.5 py-1 text-[13px] font-bold tracking-[0.03em] text-white">SIGNAL TEST (antenna covered)</p>
            ) : null}
            {box.status && box.status !== box.server_status && box.server_status !== 'OFFLINE' ? (
              <p className="mt-2 text-[13px] text-ink-600">The box itself says {box.status}; the dashboard trusts the server&apos;s own check.</p>
            ) : null}
          </section>

          <dl className="rounded-lg border border-sand-400 bg-sand-50 px-3 py-1">
            <Fact label="Last packet">{ago(box.age_s)}</Fact>
            <Fact label="Satellite fix">{box.fix ? 'Yes' : 'No'}</Fact>
            <Fact label="Satellites used / in view" mono>
              {box.sats_used ?? '–'} / {box.sats_in_view ?? '–'}
            </Fact>
            <Fact label="Average signal" mono>
              {typeof box.avg_snr === 'number' ? `${box.avg_snr.toFixed(1)} dB-Hz` : '–'}
            </Fact>
            <Fact label="Baseline" mono>
              {baseline ? `${baseline.toFixed(1)} dB-Hz` : 'learning (first 2 min with a fix)'}
            </Fact>
            <Fact label="Position" mono>
              {fmtLatLon(box.lat, box.lon)}
            </Fact>
          </dl>

          <p className="text-[14px] leading-relaxed text-ink-700">
            The box learns its normal satellite signal in its first two minutes with a fix. A drop of {ALARM_DROP_DB} dB or more, or losing the fix, reads as jamming; a fixed box that
            appears to move reads as spoofing. It shows the method on a table; at border airports it would cover the gaps where too few aircraft fly.
          </p>
          <SimulateFoil />
        </div>

        <div className="min-w-0 space-y-6">
          <section aria-labelledby="snr-title">
            <h2 id="snr-title" className="text-[17px] font-bold text-ink-900">
              Average satellite signal, last 5 minutes
            </h2>
            <p className="text-[13px] text-ink-600">C/N0 in dB-Hz. Foil over the antenna shows as a cliff below the red line.</p>
            <LineChart points={snrPoints} now={nowS} windowS={WINDOW_S} unit="dB-Hz" refs={refs} label="Average satellite signal" />
          </section>
          <section aria-labelledby="sats-title">
            <h2 id="sats-title" className="text-[17px] font-bold text-ink-900">
              Satellites used in the fix
            </h2>
            <LineChart points={satPoints} now={nowS} windowS={WINDOW_S} yDomain={[0, 14]} step decimals={0} label="Satellites used" height={140} />
          </section>
          <section aria-labelledby="bars-title" className="space-y-2">
            <h2 id="bars-title" className="text-[17px] font-bold text-ink-900">
              Signal per satellite now
            </h2>
            <SatelliteBars snr={box.snr_list} baseline={baseline} />
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
                        {alarmEv ? ' (signal test)' : ''}
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
    </div>
  )
}
