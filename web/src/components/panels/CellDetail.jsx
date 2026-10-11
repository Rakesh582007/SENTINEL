import { useEffect, useState } from 'react'
import { ApiError, api, errorText } from '../../api/client.js'
import { STANDALONE } from '../../config.js'
import { nearestAirport } from '../../data/airports.js'
import { fmtLatLon, haversineKm } from '../../lib/geo.js'
import { BAD_REASON, BAD_SHORT, hasSpoofEvidence, stateOf } from '../../lib/states.js'
import { clock, istHM } from '../../lib/time.js'
import { alertInjected, useDerived, useStore } from '../../store.js'
import { variantOf } from '../map/AircraftLayer.jsx'
import { Button, Fact, InjectedBadge, StateChip } from '../ui.jsx'
import { IncidentCard } from './IncidentsPanel.jsx'

const pct = (x) => `${Math.round((x || 0) * 100)}%`

function stateExplanation(c, cfg, windowMin) {
  const need = cfg?.min_aircraft ?? 3
  const minBad = cfg?.jam_min_bad ?? 2
  const lb = cfg?.jam_lower_bound ?? 0.15
  switch (c.state) {
    case 'insufficient':
      return `Not enough aircraft to decide: ${c.n_aircraft} seen in the last ${windowMin} min, ${need} needed. Free ADS-B coverage is thin here; this is where a Ground Sentinel helps.`
    case 'clear':
      return `${c.n_aircraft} different aircraft passed through in the last ${windowMin} min and none reported bad GPS often enough to matter.`
    case 'degraded':
      return `${c.n_bad} of ${c.n_aircraft} aircraft reported bad GPS. Jammed needs at least ${minBad} bad aircraft and a 95% lower bound of at least ${pct(lb)}; this one has ${pct(c.lower_bound)}.`
    case 'jammed':
      return `${c.n_bad} of ${c.n_aircraft} different aircraft reported bad GPS in the last ${windowMin} min. Even the cautious estimate (95% lower bound) is ${pct(c.lower_bound)}, above the ${pct(lb)} threshold, so one faulty aircraft cannot explain it.`
    case 'spoofing':
      return 'At least one aircraft here showed strong spoofing evidence (an impossible jump or several aircraft at one spot), or enough aircraft showed weaker evidence.'
    default:
      return stateOf(c.state).words
  }
}

function AircraftRow({ a }) {
  const select = useStore((s) => s.select)
  const focusOn = useStore((s) => s.focusOn)
  const v = variantOf(a)
  const status =
    v === 'lost'
      ? 'Position lost'
      : v === 'spoof'
        ? 'Spoofing flag'
        : v === 'bad'
          ? BAD_SHORT[a.bad] || 'Bad GPS'
          : 'GPS healthy'
  const tone = v === 'bad' || v === 'lost' ? '#7A4B05' : v === 'spoof' ? '#5B2A9A' : '#4B5E78'
  return (
    <li>
      <button
        type="button"
        onClick={() => {
          select('aircraft', a.hex)
          focusOn({ center: [a.lat, a.lon], zoom: 8 })
        }}
        className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left hover:bg-air-50"
      >
        <span className="min-w-0 whitespace-nowrap">
          <span className="font-data text-[14px] font-bold text-ink-900">{a.flight || a.hex.toUpperCase()}</span>
          <span className="ml-2 font-data text-[12px] text-ink-600">{a.alt_baro != null ? `${a.alt_baro.toLocaleString('en-IN')} ft` : a.on_ground ? 'ground' : ''}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          <span className="text-[13px] font-semibold" style={{ color: tone }}>
            {status}
          </span>
          {a.injected ? <InjectedBadge short /> : null}
        </span>
      </button>
    </li>
  )
}

function AiSummary({ h3 }) {
  const [state, setState] = useState({ phase: 'idle' })
  useEffect(() => setState({ phase: 'idle' }), [h3])

  const draft = async () => {
    setState({ phase: 'loading' })
    try {
      const res = await api.cellSummary(h3)
      setState({ phase: 'done', res })
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 405 || e.status === 501)) setState({ phase: 'not-built' })
      else setState({ phase: 'error', text: errorText(e) })
    }
  }

  return (
    <section className="rounded-lg border border-air-300 bg-air-50 p-3" aria-labelledby="ai-title">
      <div className="flex items-center justify-between gap-2">
        <h3 id="ai-title" className="text-[15.5px] font-bold text-ink-900">
          AI summary
        </h3>
        <Button variant="primary" size="sm" onClick={draft} disabled={state.phase === 'loading'}>
          {state.phase === 'loading' ? 'Drafting…' : state.phase === 'done' ? 'Draft again' : 'Draft AI summary'}
        </Button>
      </div>
      {state.phase === 'idle' ? (
        <p className="mt-1.5 text-[13.5px] leading-snug text-ink-600">
          Turns the facts above into a short note a controller can read in ten seconds. It only rewords them; detection stays rule-based.
        </p>
      ) : null}
      {state.phase === 'not-built' ? (
        <div className="mt-2 rounded-md border border-dashed border-air-500 bg-sand-50 p-2.5 text-[13.5px] leading-snug text-ink-700">
          <p className="font-semibold text-ink-900">Not connected yet.</p>
          <p className="mt-1">
            {STANDALONE ? 'This standalone build has no backend. ' : ''}The backend endpoint <code className="font-data text-[12px]">GET /api/cells/{'{h3}'}/summary</code> is still to be
            built. When it exists, Gemini drafts the note here from this hexagon&apos;s facts, aircraft and linked incident.
          </p>
        </div>
      ) : null}
      {state.phase === 'error' ? <p className="mt-2 text-[13.5px] font-semibold text-[#8F1F23]">Could not draft a summary: {state.text}</p> : null}
      {state.phase === 'done' ? (
        <div className="mt-2">
          <p className="whitespace-pre-line text-[14.5px] leading-relaxed text-ink-900">{state.res?.summary || 'The backend returned an empty summary.'}</p>
          <p className="mt-1.5 text-[12px] text-ink-600">
            AI-drafted{state.res?.model ? ` by ${state.res.model}` : ''}
            {state.res?.generated_ts ? ` at ${istHM(state.res.generated_ts)} IST` : ''} from the facts above. Check before sharing.
          </p>
        </div>
      ) : null}
    </section>
  )
}

export default function CellDetail({ id }) {
  const d = useDerived()
  const tick = useStore((s) => s.tick)
  const cfg = useStore((s) => s.detection)
  const clearSelection = useStore((s) => s.clearSelection)
  const focusOn = useStore((s) => s.focusOn)
  const c = d.cellsById.get(id)
  const windowMin = Math.round((tick?.window_s ?? 1200) / 60)

  const back = (
    <button type="button" onClick={clearSelection} className="text-[14px] font-semibold text-air-700 underline-offset-4 hover:underline">
      Back to warnings and incidents
    </button>
  )

  if (!c) {
    return (
      <div className="space-y-3">
        {back}
        <p className="rounded-lg border border-dashed border-sand-400 p-3 text-[14px] text-ink-600">
          This hexagon is no longer in the feed. Its aircraft aged out of the {windowMin}-minute window, or the cell size changed.
        </p>
      </div>
    )
  }

  const injected = d.injectedCells.has(id)
  const inside = d.aircraftInCell.get(id) || []
  const incident = d.incidentsByCell.get(id)
  const heading = d.alerts.filter((a) => a.kind === 'early_warning' && a.h3 === id)
  const near = nearestAirport(c.center[0], c.center[1], haversineKm)
  const reasons = Object.entries(c.reasons || {}).sort((a, b) => b[1] - a[1])
  const res = tick?.h3_res ?? 3

  return (
    <div className="space-y-4">
      {back}
      <header className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[19px] font-bold text-ink-900">Hexagon</h2>
          <StateChip state={c.state} size="lg" />
          {injected ? <InjectedBadge /> : null}
        </div>
        <p className="text-[13px] text-ink-600">
          <span className="font-data text-ink-900">{id}</span> (H3 resolution {res})
        </p>
        <p className="text-[13.5px] text-ink-700">
          Centre <span className="font-data">{fmtLatLon(c.center[0], c.center[1])}</span>
          {near ? `, ${Math.round(near.km)} km from ${near.city} (${near.icao})` : ''}.{' '}
          <button type="button" className="font-semibold text-air-700 underline-offset-4 hover:underline" onClick={() => focusOn({ center: c.center, zoom: 8 })}>
            Zoom to it
          </button>
        </p>
      </header>

      <p className="text-[14.5px] leading-relaxed text-ink-900">{stateExplanation(c, cfg, windowMin)}</p>

      <section aria-labelledby="facts-title">
        <h3 id="facts-title" className="text-[15.5px] font-bold text-ink-900">
          Last {windowMin} minutes
        </h3>
        <dl className="mt-1">
          <Fact label="Different aircraft seen" mono>
            {c.n_aircraft}
          </Fact>
          <Fact label="Reported bad GPS" mono>
            {c.n_bad}
          </Fact>
          <Fact label="Share with bad GPS" mono>
            {pct(c.frac_bad)}
          </Fact>
          <Fact label="Cautious estimate (95% lower bound)" mono>
            {pct(c.lower_bound)}
          </Fact>
          {reasons.length ? (
            <Fact label="Why they were bad">
              <span className="font-normal">{reasons.map(([k, n]) => `${BAD_REASON[k] || k} ×${n}`).join(', ')}</span>
            </Fact>
          ) : null}
          {c.n_injected ? (
            <Fact label="From simulated attacks">
              {c.n_injected} of {c.n_bad} bad aircraft
            </Fact>
          ) : null}
        </dl>
        {injected ? (
          <p className="mt-2 rounded-md bg-signal-50 px-2.5 py-1.5 text-[13px] leading-snug text-signal-900">
            Simulated data from the Attack simulator shaped this hexagon. It is not a real-world event.
          </p>
        ) : null}
      </section>

      {heading.length ? (
        <section aria-labelledby="heading-title">
          <h3 id="heading-title" className="text-[15.5px] font-bold text-ink-900">
            Heading into this hexagon
          </h3>
          <ul className="mt-1 space-y-1">
            {heading.map((a) => (
              <li key={a.id} className="flex items-baseline justify-between gap-2 text-[14px]">
                <span className="font-data font-bold">{a.flight || a.hex?.toUpperCase()}</span>
                <span className="flex items-center gap-1.5">
                  <span className="font-data tnum">{clock(a.eta_s)}</span>
                  <span className="text-ink-600">to entry</span>
                  {alertInjected(a, d) ? <InjectedBadge short /> : null}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="inside-title">
        <h3 id="inside-title" className="text-[15.5px] font-bold text-ink-900">
          Aircraft inside now ({inside.length})
        </h3>
        <p className="text-[12.5px] leading-snug text-ink-600">The counts above include every aircraft seen in the window; this list is who is inside at this moment.</p>
        {inside.length ? (
          <ul className="mt-1 divide-y divide-sand-300">
            {inside
              .slice()
              .sort((a, b) => Number(Boolean(b.bad || hasSpoofEvidence(b.spoof))) - Number(Boolean(a.bad || hasSpoofEvidence(a.spoof))))
              .map((a) => (
                <AircraftRow key={a.hex} a={a} />
              ))}
          </ul>
        ) : (
          <p className="mt-1 text-[14px] text-ink-600">None right now.</p>
        )}
      </section>

      <section aria-labelledby="incident-title" className="space-y-1.5">
        <h3 id="incident-title" className="text-[15.5px] font-bold text-ink-900">
          Linked incident
        </h3>
        {incident ? (
          <IncidentCard inc={incident} />
        ) : (
          <p className="text-[14px] text-ink-600">None. An incident opens when a hexagon turns jammed or spoofing.</p>
        )}
      </section>

      <AiSummary h3={id} />
    </div>
  )
}
