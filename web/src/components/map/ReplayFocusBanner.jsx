import { clock, istTime } from '../../lib/time.js'
import { useStore } from '../../store.js'
import { useDataElapsed } from '../panels/useDataClock.js'

/** Top of the map while an incident is being replayed: which one, and how far from its start. */
export default function ReplayFocusBanner() {
  const f = useStore((s) => s.replayFocus)
  const tick = useStore((s) => s.tick)
  const setReplayFocus = useStore((s) => s.setReplayFocus)
  const focusOn = useStore((s) => s.focusOn)
  const elapsed = useDataElapsed()
  if (!f || !tick) return null
  const now = (tick.ts || 0) + elapsed
  const dt = f.opened_ts - now
  const where = tick.mode !== 'replay' ? 'switching to the recording…' : dt > 0 ? `starts in ${clock(dt)}` : `started ${clock(-dt)} ago`
  const tone = f.kind === 'spoofing' ? '#7B45C4' : '#B5292E'
  return (
    <div className="pointer-events-none absolute inset-x-0 top-2 z-[870] flex justify-center px-2">
      <div className="pointer-events-auto flex max-w-[680px] flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border bg-sand-50/95 px-3 py-1.5 text-[13.5px] shadow-float" style={{ borderColor: tone, borderLeftWidth: 5 }} role="status">
        <span className="font-bold text-ink-900">
          Replaying incident #{f.num} · {f.kind === 'jamming' ? 'GPS jamming' : 'suspected spoofing'}
          {f.place ? `, ${f.place}` : ''}
        </span>
        <span className="text-ink-700">
          opened <span className="font-data tnum">{istTime(f.opened_ts)}</span> IST · <span className="font-semibold">{where}</span>
        </span>
        {f.bounds ? (
          <button type="button" className="text-[13px] font-semibold text-air-700 hover:underline" onClick={() => focusOn({ bounds: f.bounds, maxZoom: 8 })}>
            Zoom to it
          </button>
        ) : null}
        <button type="button" className="text-[13px] font-semibold text-ink-600 hover:underline" onClick={() => setReplayFocus(null)}>
          Done
        </button>
      </div>
    </div>
  )
}
