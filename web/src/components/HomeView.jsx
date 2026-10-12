import { sentinelOf, stateOf } from '../lib/states.js'
import { derive, useStore, viewTick } from '../store.js'

function HexIcon() {
  return (
    <svg width="44" height="44" viewBox="0 0 44 44" aria-hidden="true">
      <path d="M22 4l15.6 9v18L22 40 6.4 31V13z" fill="#E5484D33" stroke="#E5484D" strokeWidth="2.4" />
      <path d="M22 13.5c.6 0 1 .7 1 1.6v3.7l5.7 3.2v1.4l-5.7-1.7v3.3l1.7 1.3v1.1l-2.7-.7-2.7.7v-1.1l1.7-1.3v-3.3l-5.7 1.7v-1.4l5.7-3.2v-3.7c0-.9.4-1.6 1-1.6z" fill="#13294B" />
    </svg>
  )
}
function TargetIcon() {
  return (
    <svg width="44" height="44" viewBox="0 0 44 44" aria-hidden="true">
      <circle cx="22" cy="22" r="15" fill="#F26B1D1f" stroke="#D2560F" strokeWidth="2.4" strokeDasharray="3 5" strokeLinecap="round" />
      <circle cx="22" cy="22" r="7" fill="none" stroke="#D2560F" strokeWidth="2.4" />
      <circle cx="22" cy="22" r="2.4" fill="#D2560F" />
    </svg>
  )
}
function AntennaIcon() {
  return (
    <svg width="44" height="44" viewBox="0 0 44 44" aria-hidden="true">
      <rect x="11" y="24" width="22" height="13" rx="2.5" fill="#DDEAF5" stroke="#1E5AA8" strokeWidth="2.2" />
      <path d="M22 24V13" stroke="#1E5AA8" strokeWidth="2.2" />
      <path d="M15 11a9.5 9.5 0 0 1 14 0M11.5 7.5a14.5 14.5 0 0 1 21 0" fill="none" stroke="#1E5AA8" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="16" cy="30.5" r="1.8" fill="#2EAF6E" />
    </svg>
  )
}

function Card({ id, icon, title, blurb, children }) {
  const setTab = useStore((s) => s.setTab)
  return (
    <button
      type="button"
      onClick={() => setTab(id)}
      className="group flex min-h-[250px] min-w-0 flex-col rounded-xl border-2 border-air-300 bg-sand-50 p-5 text-left shadow-float transition-colors hover:border-air-600 hover:bg-air-50 focus-visible:border-air-600"
    >
      <div className="flex items-center gap-3">
        {icon}
        <h2 className="text-[22px] font-bold leading-tight text-ink-900">{title}</h2>
      </div>
      <p className="mt-3 text-[15.5px] leading-relaxed text-ink-700">{blurb}</p>
      <div className="mt-4 flex-1 space-y-1.5 text-[15px] text-ink-900">{children}</div>
      <span className="mt-4 text-[15px] font-semibold text-air-700 underline-offset-4 group-hover:underline">Open {title.toLowerCase()}</span>
    </button>
  )
}

const Line = ({ dot, children }) => (
  <p className="flex items-center gap-2">
    {dot ? <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: dot }} aria-hidden="true" /> : null}
    <span>{children}</span>
  </p>
)

/** Main dashboard: three sections to choose from, each with its state right now. */
export default function HomeView() {
  const raw = useStore((s) => s.tick)
  const tick = viewTick(raw, 'real') // Live airspace numbers never include simulated attacks
  const d = derive(tick)
  const counts = tick?.stats?.cells || {}
  const jammed = counts.jammed || 0
  const spoofing = counts.spoofing || 0
  const warnings = d.alerts.filter((a) => a.kind === 'early_warning').length
  const liveAttacks = (raw?.attacks || []).filter((a) => a.live).length
  const box = tick?.sentinel?.[0]
  const s = box ? sentinelOf(box.server_status) : null

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8 lg:py-12">
        <h1 className="text-[28px] font-bold text-ink-900">Main dashboard</h1>
        <p className="mt-1 max-w-2xl text-[16px] leading-relaxed text-ink-700">
          Pick a section.
        </p>
        <div className="mt-6 grid gap-5 md:grid-cols-3">
          <Card
            id="airspace"
            icon={<HexIcon />}
            title="Live airspace"
            blurb="Real aircraft over North India and how much each one trusts its GPS. Areas where several planes lose GPS turn red."
          >
            {tick ? (
              <>
                <Line>{tick.stats?.aircraft ?? 0} aircraft on the map ({tick.mode === 'replay' ? 'recorded replay' : 'live'})</Line>
                <Line dot={jammed ? stateOf('jammed').color : stateOf('clear').color}>
                  {jammed ? `${jammed} jammed ${jammed === 1 ? 'area' : 'areas'}` : 'No jammed areas'}
                  {spoofing ? `, ${spoofing} spoofed` : ''}
                </Line>
                <Line>{warnings ? `${warnings} ${warnings === 1 ? 'plane' : 'planes'} heading into trouble` : 'No planes heading into trouble'}</Line>
              </>
            ) : (
              <Line>Waiting for data…</Line>
            )}
          </Card>
          <Card
            id="simulator"
            icon={<TargetIcon />}
            title="Attack simulator"
            blurb="Judges place a pretend jammer or fake a plane's position, and watch the system catch it. Data only; nothing is transmitted."
          >
            <Line dot={liveAttacks ? '#F26B1D' : undefined}>{liveAttacks ? `${liveAttacks} test ${liveAttacks === 1 ? 'attack' : 'attacks'} running` : 'No test attacks running'}</Line>
          </Card>
          <Card
            id="sentinel"
            icon={<AntennaIcon />}
            title="Ground sentinel"
            blurb="Our own GPS box on the table. Cover its antenna with foil and the signal drop shows up here as jamming."
          >
            {box ? (
              <>
                <Line dot={s.color}>
                  Status: <span className="font-bold">{s.label}</span>
                </Line>
                {box.server_reason ? <Line>{box.server_reason[0].toUpperCase() + box.server_reason.slice(1)}</Line> : null}
              </>
            ) : (
              <Line>Not connected yet</Line>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
