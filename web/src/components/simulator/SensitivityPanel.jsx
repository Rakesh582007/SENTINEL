import { useState } from 'react'
import { api, errorText } from '../../api/client.js'
import { CELL_STATES, stateOf } from '../../lib/states.js'
import { useStore } from '../../store.js'
import { Button, Slider } from '../ui.jsx'
import { useDebouncedCallback } from './useDebouncedCallback.js'

const CELL_SIZE = { 2: 'large, about 86,700 km²', 3: 'medium, about 12,400 km²', 4: 'small, about 1,800 km²' }

/** Detection thresholds judges can move (PATCH /api/config/detection), with the live hexagon count beside them. */
export default function SensitivityPanel() {
  const cfg = useStore((s) => s.detection)
  const setDetection = useStore((s) => s.setDetection)
  const tick = useStore((s) => s.tick)
  const toast = useStore((s) => s.toast)
  const [draft, setDraft] = useState({})
  const v = { ...(cfg || {}), ...draft }

  const send = useDebouncedCallback(async (changes) => {
    try {
      const next = await api.patchDetection(changes)
      setDetection(next)
      setDraft((dft) => {
        const out = { ...dft }
        for (const k of Object.keys(changes)) if (out[k] === changes[k]) delete out[k]
        return out
      })
    } catch (e) {
      toast(`Threshold not changed: ${errorText(e)}`, 'error')
      setDraft({})
    }
  }, 300)

  const change = (key, value) => {
    setDraft((dft) => ({ ...dft, [key]: value }))
    send({ [key]: value })
  }

  const reset = async () => {
    try {
      setDetection(await api.resetDetection())
      setDraft({})
      toast('Detection thresholds back to defaults.', 'ok')
    } catch (e) {
      toast(errorText(e), 'error')
    }
  }

  const counts = tick?.stats?.cells || {}
  const disabled = !cfg

  return (
    <details className="group rounded-lg border border-sand-400 bg-sand-50 p-3">
      <summary className="cursor-pointer list-none text-[17px] font-bold text-ink-900">
        <span className="mr-1.5 inline-block transition-transform group-open:rotate-90" aria-hidden="true">
          ▸
        </span>
        Detection sensitivity
      </summary>
      <div className="mt-3 space-y-4">
        <p className="text-[13.5px] leading-snug text-ink-700">
          Move these to see the trade-off: catch more interference, or raise fewer false alarms. Each change applies from the next tick (5 s).
        </p>
        <div className="rounded-md bg-sand-200 px-2.5 py-2" aria-live="polite">
          <p className="text-[12.5px] font-semibold text-ink-700">Hexagons right now</p>
          <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
            {CELL_STATES.map((st) => (
              <li key={st} className="flex items-center gap-1 text-[13px] text-ink-900">
                <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: stateOf(st).color }} aria-hidden="true" />
                {stateOf(st).label} <span className="font-data tnum">{counts[st] || 0}</span>
              </li>
            ))}
          </ul>
        </div>
        <Slider
          id="cfg-nacp"
          label="Bad GPS threshold (NACp)"
          min={5}
          max={9}
          value={v.nacp_bad ?? 7}
          disabled={disabled}
          onChange={(x) => change('nacp_bad', x)}
          format={(x) => `≤ ${x}`}
          hint="An aircraft reporting NACp at or below this counts as bad. Higher catches more, and flags more healthy aircraft."
        />
        <Slider
          id="cfg-min"
          label="Aircraft needed per hexagon"
          min={2}
          max={6}
          value={v.min_aircraft ?? 3}
          disabled={disabled}
          onChange={(x) => change('min_aircraft', x)}
          format={(x) => `${x}`}
          hint="Fewer decides in sparse areas, but one faulty aircraft weighs more."
        />
        <Slider
          id="cfg-window"
          label="Detection window"
          min={5}
          max={30}
          value={Math.round((v.jam_window_s ?? 1200) / 60)}
          disabled={disabled}
          onChange={(x) => change('jam_window_s', x * 60)}
          format={(x) => `${x} min`}
          hint="Longer gathers more aircraft per hexagon but is slower to clear."
        />
        <Slider
          id="cfg-res"
          label="Cell size"
          min={2}
          max={4}
          value={v.h3_res ?? 3}
          disabled={disabled}
          onChange={(x) => change('h3_res', x)}
          format={(x) => CELL_SIZE[x] || x}
          hint="Bigger cells collect more aircraft; smaller ones locate trouble more precisely."
        />
        <Slider
          id="cfg-spoof"
          label="Weak-evidence aircraft for a purple hexagon"
          min={1}
          max={5}
          value={v.spoof_cell_min_flags ?? 2}
          disabled={disabled}
          onChange={(x) => change('spoof_cell_min_flags', x)}
          format={(x) => `${x}`}
          hint="Strong evidence (an impossible jump) turns a hexagon purple on its own."
        />
        <Button onClick={reset} disabled={disabled}>
          Reset to defaults
        </Button>
      </div>
    </details>
  )
}
