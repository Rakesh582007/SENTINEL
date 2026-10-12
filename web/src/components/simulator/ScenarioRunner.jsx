import { useEffect, useState } from 'react'
import { api, errorText } from '../../api/client.js'
import { duration } from '../../lib/time.js'
import { useStore } from '../../store.js'
import { Button } from '../ui.jsx'

const firstSentence = (text) => {
  if (!text) return ''
  const m = String(text).match(/^.*?[.!?](\s|$)/)
  return (m ? m[0] : String(text)).trim()
}

/** "Run scripted demo": scenarios/demo1.json fires attacks at fixed replay offsets. */
export default function ScenarioRunner() {
  const tick = useStore((s) => s.tick)
  const toast = useStore((s) => s.toast)
  const [list, setList] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .scenarios()
      .then((r) => setList(r.available || []))
      .catch(() => setList([]))
  }, [])

  const running = tick?.scenario
  const run = async (id) => {
    setBusy(true)
    try {
      await api.runScenario(id)
      toast(`Scripted demo ${id} started. Its attacks fire on the replay clock.`, 'ok')
    } catch (e) {
      toast(`Could not start ${id}: ${errorText(e)}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby="scenario-title" className="space-y-2">
      <h2 id="scenario-title" className="text-[17px] font-bold text-ink-900">
        Scripted demo
      </h2>
      {running ? (
        <div className="rounded-md border border-signal-500 bg-signal-50 p-2.5 text-[13.5px] leading-snug text-signal-900">
          <p className="font-semibold">
            {running.id} running: {running.fired?.length || 0} fired, {running.remaining} to go
            {running.next_ts && tick ? `, next in ${duration(running.next_ts - tick.ts)}` : ''}.
          </p>
          {running.fired?.length ? <p className="mt-0.5 font-data text-[12px]">{running.fired.join(', ')}</p> : null}
        </div>
      ) : null}
      {list === null ? <p className="text-[13.5px] text-ink-600">Loading scenarios…</p> : null}
      {list?.length === 0 ? <p className="text-[13.5px] text-ink-600">No scenarios found in scenarios/.</p> : null}
      {list?.map((sc) => (
        <div key={sc.id} className="flex items-start justify-between gap-3">
          <p className="text-[13px] leading-snug text-ink-700">
            <span className="font-semibold text-ink-900">{sc.id}</span>: {sc.events} timed attacks. {firstSentence(sc.description)}
          </p>
          <Button size="sm" onClick={() => run(sc.id)} disabled={busy || Boolean(running)}>
            Run
          </Button>
        </div>
      ))}
    </section>
  )
}
