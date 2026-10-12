import L from 'leaflet'
import { useMemo } from 'react'
import { Circle, Marker, Pane, Tooltip } from 'react-leaflet'
import { incidentCentre, incidentNumber, replayIncident } from '../../lib/incidents.js'
import { useDerived, useStore } from '../../store.js'

const STYLE = {
  jamming: { color: '#B5292E', weight: 1.8, opacity: 0.85, dashArray: '8 6', fillColor: '#E5484D', fillOpacity: 0.04, interactive: false },
}

const icons = new Map()
function chipIcon(text, kind, injected, active) {
  const key = `${text}|${kind}|${injected}|${active}`
  if (!icons.has(key)) {
    const cls = ['zone-chip', kind === 'spoofing' ? 'spoof' : '', injected ? 'inj' : '', active ? 'active' : ''].filter(Boolean).join(' ')
    icons.set(key, L.divIcon({ className: 'leaflet-div-icon bare', iconSize: [0, 0], html: `<div class="${cls}">${text}${injected ? ' <span class="inj">INJECTED</span>' : ''}</div>` }))
  }
  return icons.get(key)
}

function Chip({ inc, at, active, cellsById }) {
  const handlers = useMemo(
    () => ({
      click: (e) => {
        L.DomEvent.stopPropagation(e)
        replayIncident(inc, cellsById)
      },
    }),
    [inc, cellsById],
  )
  const n = incidentNumber(inc)
  // The chip carries the state word, so the hexagons under an incident need no label of their own.
  const label = `${inc.kind === 'jamming' ? 'Jammed' : 'Spoofing'} #${n}${inc.open ? '' : ' (ended)'}`
  return (
    <Marker position={at} icon={chipIcon(label, inc.kind, Boolean(inc.injected), active)} eventHandlers={handlers} keyboard={false} zIndexOffset={500}>
      <Tooltip direction="top" offset={[0, -12]} className="st-tip">
        <b>{inc.kind === 'jamming' ? 'Jamming' : 'Suspected spoofing'} incident #{n}</b>
        {inc.injected ? ' (INJECTED TEST ATTACK)' : ''}
        <br />
        {inc.kind === 'jamming' && inc.est_radius_km
          ? `Dashed circle: approximate area for investigation, about ${Math.round(inc.est_radius_km)} km radius.`
          : 'Affected aircraft are in the purple hexagon.'}
        <br />
        Click to replay it.
      </Tooltip>
    </Marker>
  )
}

/** Open incidents: a dashed "approximate area for investigation" circle (jamming) and a small
 *  numbered chip. The full wording lives in the tooltip and the incident card, not on the map. */
export default function IncidentCircles() {
  const d = useDerived()
  const focusId = useStore((s) => s.replayFocus?.id)
  const shown = d.incidents.filter((i) => i.open || i.id === focusId)
  const circles = shown.filter((i) => i.kind === 'jamming' && i.est_lat != null && i.est_lon != null && i.est_radius_km)
  return (
    <>
      <Pane name="incidents" style={{ zIndex: 410 }}>
        {circles.map((i) => (
          <Circle key={i.id} center={[i.est_lat, i.est_lon]} radius={i.est_radius_km * 1000} pathOptions={STYLE.jamming} />
        ))}
      </Pane>
      <Pane name="incident-labels" style={{ zIndex: 630 }}>
        {shown.map((i) => {
          const c = incidentCentre(i)
          if (!c) return null
          const at = i.kind === 'jamming' && i.est_radius_km ? [c[0] + i.est_radius_km / 111.2, c[1]] : c
          return <Chip key={i.id} inc={i} at={at} active={i.id === focusId} cellsById={d.cellsById} />
        })}
      </Pane>
    </>
  )
}
