import L from 'leaflet'
import { Circle, Marker, Pane } from 'react-leaflet'
import { useDerived } from '../../store.js'

const STYLE = { color: '#B5292E', weight: 2, opacity: 0.9, dashArray: '10 7', fillColor: '#E5484D', fillOpacity: 0.05, interactive: false }

const icons = new Map()
function labelIcon(text, injected) {
  const key = `${text}|${injected}`
  if (!icons.has(key)) {
    icons.set(
      key,
      L.divIcon({
        className: 'leaflet-div-icon bare',
        iconSize: [0, 0],
        html: `<div class="zone-label"><b>Approximate area for investigation</b><br>${text}${injected ? ' <span class="inj">INJECTED</span>' : ''}</div>`,
      }),
    )
  }
  return icons.get(key)
}

/** Where a jammer might be, from where aircraft first reported trouble.
 *  Always worded as an approximate area for investigation, never a location. */
export default function IncidentCircles() {
  const d = useDerived()
  const circles = d.incidents.filter((i) => i.open && i.kind === 'jamming' && i.est_lat != null && i.est_lon != null && i.est_radius_km)
  return (
    <>
      <Pane name="incidents" style={{ zIndex: 410 }}>
        {circles.map((i) => (
          <Circle key={i.id} center={[i.est_lat, i.est_lon]} radius={i.est_radius_km * 1000} pathOptions={STYLE} />
        ))}
      </Pane>
      <Pane name="incident-labels" style={{ zIndex: 625 }}>
      {circles.map((i) => (
        <Marker
          key={`${i.id}-label`}
          position={[i.est_lat + i.est_radius_km / 111.2, i.est_lon]}
          icon={labelIcon(`${i.id}, about ${Math.round(i.est_radius_km)} km radius`, i.injected)}
          interactive={false}
          keyboard={false}
        />
      ))}
      </Pane>
    </>
  )
}
