import { stateOf } from '../../lib/states.js'
import { clock } from '../../lib/time.js'
import { alertInjected, useDerived, useStore, useViewTick } from '../../store.js'
import { InjectedBadge, SectionTitle } from '../ui.jsx'
import { useDataElapsed } from './useDataClock.js'

function boundsOf(points) {
  let s = 90
  let n = -90
  let w = 180
  let e = -180
  for (const [lat, lon] of points) {
    s = Math.min(s, lat)
    n = Math.max(n, lat)
    w = Math.min(w, lon)
    e = Math.max(e, lon)
  }
  return [
    [s, w],
    [n, e],
  ]
}

function WarningCard({ a, injected, elapsed }) {
  const focusOn = useStore((s) => s.focusOn)
  const select = useStore((s) => s.select)
  const st = stateOf(a.cell_state)
  const eta = Math.max(0, (a.eta_s ?? 0) - elapsed)
  const soon = eta <= 300
  const open = () => {
    if (a.path?.length) focusOn({ bounds: boundsOf(a.path), maxZoom: 8 })
    if (a.hex) select('aircraft', a.hex)
  }
  return (
    <li>
      <button
        type="button"
        onClick={open}
        className="block w-full rounded-lg border bg-sand-50 p-3 text-left transition-colors hover:bg-air-50"
        style={{ borderColor: st.color, borderWidth: 1.5 }}
      >
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12.5px] font-bold text-ink-700">Early warning</span>
          <span className="rounded px-1.5 text-[12px] font-semibold leading-[1.6]" style={{ color: st.ink, background: `${st.color}24` }}>
            into {st.label.toLowerCase()} area
          </span>
          {soon ? <span className="rounded bg-[#E5484D] px-1.5 text-[12px] font-bold leading-[1.6] text-white">under 5 min</span> : null}
          {injected ? <InjectedBadge /> : null}
        </div>
        <div className="mt-1.5 flex items-baseline justify-between gap-3">
          <span className="font-data text-[17px] font-bold text-ink-900">{a.flight || a.hex?.toUpperCase()}</span>
          <span className="text-right">
            <span className="font-data text-[20px] font-bold text-ink-900 tnum">{clock(eta)}</span>
            <span className="ml-1 text-[12px] text-ink-600">to entry</span>
          </span>
        </div>
        <p className="mt-1 text-[14px] leading-snug text-ink-700">{a.message}</p>
      </button>
    </li>
  )
}

function SentinelCard({ a }) {
  const setTab = useStore((s) => s.setTab)
  const tone = a.kind === 'sentinel_spoof' ? '#9B5DE5' : '#E5484D'
  return (
    <li>
      <button
        type="button"
        onClick={() => setTab('sentinel')}
        className="block w-full rounded-lg border bg-sand-50 p-3 text-left transition-colors hover:bg-air-50"
        style={{ borderColor: tone, borderWidth: 1.5 }}
      >
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[12.5px] font-bold text-ink-700">Ground sentinel</span>
          <span className="rounded bg-ink-900 px-1.5 text-[11.5px] font-bold leading-[1.6] text-white">{a.label || 'SIGNAL TEST'}</span>
        </div>
        <p className="mt-1.5 text-[14.5px] font-semibold leading-snug text-ink-900">{a.message}</p>
      </button>
    </li>
  )
}

export default function AlertsPanel() {
  const d = useDerived()
  const tick = useViewTick()
  const setTab = useStore((s) => s.setTab)
  const elapsed = useDataElapsed()
  const alerts = d.alerts

  return (
    <section aria-labelledby="alerts-title" className="space-y-2.5">
      <SectionTitle aside={tick ? `${alerts.length} active` : null}>
        <span id="alerts-title">Early warnings</span>
      </SectionTitle>
      {alerts.length ? (
        <ul className="space-y-2" aria-live="polite">
          {alerts.map((a) =>
            a.kind === 'early_warning' ? (
              <WarningCard key={a.id} a={a} injected={alertInjected(a, d)} elapsed={elapsed} />
            ) : (
              <SentinelCard key={a.id} a={a} />
            ),
          )}
        </ul>
      ) : (
        <div className="rounded-lg border border-dashed border-sand-400 p-3 text-[14px] leading-snug text-ink-600">
          <p>No aircraft is heading into a jammed or spoofed hexagon in the next 15 minutes.</p>
          <button type="button" className="mt-2 font-semibold text-air-700 underline-offset-4 hover:underline" onClick={() => setTab('simulator')}>
            Inject a test jammer in the Attack simulator
          </button>
        </div>
      )}
      <p className="text-[12.5px] leading-snug text-ink-600">
        Warnings are for controllers on this dashboard. The system is receive-only and never transmits to aircraft.
      </p>
    </section>
  )
}
