import { CELL_STATES, stateOf } from '../lib/states.js'
import { useStore } from '../store.js'

function Swatch({ state }) {
  const s = stateOf(state)
  const quiet = state === 'insufficient'
  return (
    <span
      className="inline-block h-3 w-4 rounded-sm"
      style={{ background: quiet ? 'rgba(107,122,144,0.12)' : `${s.color}88`, border: `1.5px ${quiet ? 'dashed' : 'solid'} ${s.color}` }}
      aria-hidden="true"
    />
  )
}

function PlaneKey({ ring, hollow }) {
  return (
    <svg width="18" height="18" viewBox="-1 -1 26 26" aria-hidden="true">
      {ring ? <circle cx="12" cy="12" r="11" fill="none" stroke={ring} strokeWidth="2.6" strokeDasharray={hollow ? '3 2.4' : undefined} /> : null}
      <path
        d="M12 1.6c.8 0 1.4 1 1.4 2.3v5.3l8.1 4.6v2l-8.1-2.4v4.7l2.4 1.8v1.6L12 20.5l-3.8 1v-1.6l2.4-1.8v-4.7L2.5 15.8v-2l8.1-4.6V3.9c0-1.3.6-2.3 1.4-2.3z"
        transform="translate(12 12) scale(0.8) translate(-12 -12)"
        fill={hollow ? '#FBF8F1' : '#2C4467'}
        stroke="#2C4467"
        strokeWidth={hollow ? 1.6 : 0.6}
      />
    </svg>
  )
}

/** Bottom strip of the map: what every colour and symbol means, and whose data it is. */
export default function Legend() {
  const showInsufficient = useStore((s) => s.showInsufficient)
  const toggleInsufficient = useStore((s) => s.toggleInsufficient)
  const basemap = useStore((s) => s.basemap)
  const tick = useStore((s) => s.tick)
  const credits = tick?.credits || { 'adsb.fi': 'https://adsb.fi', 'adsb.lol': 'https://adsb.lol' }
  const sources = ['adsb.fi', 'adsb.lol'].filter((k) => credits[k])

  return (
    <div className="pointer-events-auto flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-lg border border-sand-400 bg-sand-50/95 px-3 py-2 text-[13px] text-ink-700 shadow-float">
      <ul className="flex flex-wrap items-center gap-x-3 gap-y-1" aria-label="Hexagon states">
        {CELL_STATES.map((st) => (
          <li key={st} className="flex items-center gap-1.5">
            <Swatch state={st} />
            {st === 'insufficient' ? (
              <label className="flex cursor-pointer items-center gap-1">
                {stateOf(st).label}
                <input type="checkbox" className="ml-0.5 accent-air-600" checked={showInsufficient} onChange={toggleInsufficient} aria-label="Show hexagons with too few aircraft" />
              </label>
            ) : (
              stateOf(st).label
            )}
          </li>
        ))}
      </ul>
      <ul className="flex flex-wrap items-center gap-x-3 gap-y-1" aria-label="Aircraft symbols">
        <li className="flex items-center gap-1">
          <PlaneKey /> Aircraft
        </li>
        <li className="flex items-center gap-1">
          <PlaneKey ring="#E8A33C" /> Bad GPS
        </li>
        <li className="flex items-center gap-1">
          <PlaneKey ring="#9B5DE5" /> Spoofing flag
        </li>
        <li className="flex items-center gap-1">
          <PlaneKey ring="#E8A33C" hollow /> Last known position
        </li>
        <li className="flex items-center gap-1">
          <span className="rounded px-1 font-data text-[9.5px] font-bold text-signal-900" style={{ background: '#F26B1D' }}>
            INJECTED
          </span>
          Simulated
        </li>
      </ul>
      <p className="ml-auto text-[12px] text-ink-600">
        Aircraft data:{' '}
        {sources.map((k, i) => (
          <span key={k}>
            <a className="font-semibold text-air-700 underline-offset-2 hover:underline" href={credits[k]} target="_blank" rel="noreferrer">
              {k}
            </a>
            {i < sources.length - 1 ? ', ' : ''}
          </span>
        ))}
        . Boundaries: Natural Earth (India view)
        {basemap === 'tiles' ? (
          <>
            . Tiles ©{' '}
            <a className="underline-offset-2 hover:underline" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
              OpenStreetMap
            </a>
            , ©{' '}
            <a className="underline-offset-2 hover:underline" href="https://carto.com/attributions" target="_blank" rel="noreferrer">
              CARTO
            </a>
          </>
        ) : null}
        .
      </p>
    </div>
  )
}
