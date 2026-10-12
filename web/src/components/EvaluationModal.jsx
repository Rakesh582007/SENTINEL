import { useEffect, useRef, useState } from 'react'
import { api, errorText } from '../api/client.js'
import { istTime } from '../lib/time.js'
import { useStore } from '../store.js'

const OUTCOME = {
  detected: { label: 'Detected', color: '#2EAF6E', ink: '#16613A' },
  missed: { label: 'Missed', color: '#E5484D', ink: '#8F1F23' },
  undetectable: { label: 'Too few aircraft', color: '#6B7A90', ink: '#3E4A5C' },
  pending: { label: 'Pending', color: '#4F86C0', ink: '#143E73' },
}

function Tile({ label, value, note }) {
  return (
    <div className="min-w-0 rounded-lg border border-sand-400 bg-sand-50 p-3">
      <div className="text-[13.5px] text-ink-600">{label}</div>
      <div className="mt-0.5 font-data text-[30px] font-bold leading-tight text-ink-900">{value}</div>
      {note ? <div className="text-[12.5px] leading-snug text-ink-600">{note}</div> : null}
    </div>
  )
}

export default function EvaluationModal() {
  const open = useStore((s) => s.evaluationOpen)
  const setOpen = useStore((s) => s.setEvaluationOpen)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const closeRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    let alive = true
    const load = () =>
      api
        .evaluation()
        .then((r) => {
          if (!alive) return
          setData(r)
          setError(null)
        })
        .catch((e) => alive && setError(errorText(e)))
    load()
    const t = window.setInterval(load, 5000)
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    closeRef.current?.focus()
    return () => {
      alive = false
      window.clearInterval(t)
      window.removeEventListener('keydown', onKey)
    }
  }, [open, setOpen])

  if (!open) return null
  const scored = data ? data.detected + data.missed : 0

  return (
    <div className="fixed inset-0 z-[1600] flex items-start justify-center overflow-y-auto bg-ink-900/40 p-4 pt-[8vh]" onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
      <div role="dialog" aria-modal="true" aria-labelledby="eval-title" className="w-full max-w-3xl rounded-xl border border-sand-400 bg-sand-100 p-5 shadow-float">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="eval-title" className="text-[22px] font-bold text-ink-900">
              Evaluation
            </h2>
            <p className="text-[14px] text-ink-600">Measured against the simulated attacks injected since the last mode switch.</p>
          </div>
          <button ref={closeRef} type="button" onClick={() => setOpen(false)} className="rounded-md border border-sand-400 px-3 py-1 text-[14px] font-semibold text-ink-700 hover:bg-air-50">
            Close
          </button>
        </div>

        {error ? <p className="mt-4 text-[14px] font-semibold text-[#8F1F23]">Could not load the evaluation: {error}</p> : null}
        {!data && !error ? <p className="mt-4 text-[14px] text-ink-600">Loading…</p> : null}

        {data ? (
          <>
            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
              <Tile label="Detected" value={scored ? `${data.detected} of ${scored}` : '–'} note={data.detection_rate != null ? `${Math.round(data.detection_rate * 100)}% of scored attacks` : 'no scored attacks yet'} />
              <Tile label="Median time to detect" value={data.median_time_to_detect_s != null ? `${Math.round(data.median_time_to_detect_s)} s` : '–'} note="from attack start to alarm" />
              <Tile label="Too few aircraft" value={data.undetectable} note="not counted as misses" />
              <Tile label="Unexplained alarms" value={data.unexplained_real_data ?? data.unexplained_alarms} note="on real data, may be real" />
            </div>
            {data.pending ? <p className="mt-2 text-[13.5px] text-ink-700">{data.pending} still pending: each attack gets 5 minutes to be detected.</p> : null}

            {data.per_event?.length ? (
              <div className="mt-4 overflow-x-auto rounded-lg border border-sand-400">
                <table className="w-full min-w-[560px] text-left text-[14px]">
                  <thead className="bg-sand-200 text-[13px] text-ink-700">
                    <tr>
                      <th className="px-3 py-2 font-semibold">Attack</th>
                      <th className="px-3 py-2 font-semibold">Started</th>
                      <th className="px-3 py-2 font-semibold">Outcome</th>
                      <th className="px-3 py-2 text-right font-semibold">Time to detect</th>
                      <th className="px-3 py-2 text-right font-semibold">Most aircraft inside</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-sand-300 bg-sand-50">
                    {data.per_event.map((e, i) => {
                      const o = OUTCOME[e.outcome] || OUTCOME.pending
                      return (
                        <tr key={`${e.attack_id}-${i}`}>
                          <td className="px-3 py-2">
                            <span className="font-data text-[13px] font-bold">{e.attack_id}</span> <span className="text-ink-700">{e.kind === 'jamming' ? 'jamming' : 'spoofing'}</span>
                          </td>
                          <td className="px-3 py-2 font-data text-[13px] tnum">{istTime(e.start_ts)}</td>
                          <td className="px-3 py-2">
                            <span className="inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[13px] font-semibold" style={{ borderColor: o.color, color: o.ink, background: `${o.color}1f` }}>
                              <span className="h-2 w-2 rounded-full" style={{ background: o.color }} aria-hidden="true" />
                              {o.label}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-right font-data text-[13px] tnum">{e.time_to_detect_s != null ? `${Math.round(e.time_to_detect_s)} s` : '–'}</td>
                          <td className="px-3 py-2 text-right font-data text-[13px] tnum">{e.kind === 'jamming' ? e.max_aircraft_inside ?? '–' : '–'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="mt-4 rounded-lg border border-dashed border-sand-400 p-3 text-[14px] text-ink-600">
                No simulated attacks yet. Start one in the Attack simulator, or run the scripted demo, then come back here.
              </p>
            )}
            <p className="mt-3 text-[12.5px] leading-snug text-ink-600">{data.note || 'Unexplained alarms on live data may be real interference; they are not counted as false alarms.'}</p>
          </>
        ) : null}
      </div>
    </div>
  )
}
