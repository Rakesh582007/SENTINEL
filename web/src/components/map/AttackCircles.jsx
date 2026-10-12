import L from 'leaflet'
import { Circle, Marker, Pane } from 'react-leaflet'
import { useDerived, useStore } from '../../store.js'

const LIVE = { color: '#D2560F', weight: 2.2, opacity: 0.95, dashArray: '3 7', lineCap: 'round', fillColor: '#F26B1D', fillOpacity: 0.06, interactive: false }
const OFF = { ...LIVE, color: '#9C8B66', fillOpacity: 0, opacity: 0.8 }

const icons = new Map()
export function attackLabelIcon(text) {
  if (!icons.has(text)) {
    icons.set(
      text,
      L.divIcon({
        className: 'leaflet-div-icon bare',
        iconSize: [0, 0],
        html: `<div class="attack-label"><span class="inj">INJECTED TEST ATTACK</span> ${text}</div>`,
      }),
    )
  }
  return icons.get(text)
}

/** Every simulated jammer on the map, on every tab. The one being edited in the
 *  simulator is drawn by JammerEditor instead. */
export default function AttackCircles() {
  const d = useDerived()
  const editing = useStore((s) => (s.tab === 'simulator' ? s.jammer.attackId : null))
  const jams = d.attacks.filter((a) => a.kind === 'jamming' && a.center && a.id !== editing)
  return (
    <>
      <Pane name="attacks" style={{ zIndex: 415 }}>
        {jams.map((a) => (
          <Circle key={a.id} center={a.center} radius={a.radius_km * 1000} pathOptions={a.live ? LIVE : OFF} />
        ))}
      </Pane>
      <Pane name="attack-labels" style={{ zIndex: 626 }}>
        {jams.map((a) => (
          <Marker
            key={`${a.id}-label`}
            position={[a.center[0] - a.radius_km / 111.2, a.center[1]]}
            icon={attackLabelIcon(`${a.id}${a.live ? '' : ', switched off'}`)}
            interactive={false}
            keyboard={false}
          />
        ))}
      </Pane>
    </>
  )
}
