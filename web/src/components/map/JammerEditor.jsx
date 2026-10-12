import L from 'leaflet'
import { useMemo } from 'react'
import { Circle, Marker, Pane } from 'react-leaflet'
import { api, errorText } from '../../api/client.js'
import { useDerived, useStore } from '../../store.js'
import { attackLabelIcon } from './AttackCircles.jsx'

const DRAFT = { color: '#1E5AA8', weight: 2.2, opacity: 0.95, dashArray: '8 6', fillColor: '#1E5AA8', fillOpacity: 0.07, interactive: false }
const LIVE = { color: '#D2560F', weight: 2.6, opacity: 1, dashArray: '3 7', lineCap: 'round', fillColor: '#F26B1D', fillOpacity: 0.08, interactive: false }
const OFF = { ...LIVE, color: '#9C8B66', fillOpacity: 0, opacity: 0.85 }

const handleIcon = (started) =>
  L.divIcon({
    className: 'leaflet-div-icon bare jammer-handle',
    iconSize: [34, 34],
    iconAnchor: [17, 17],
    html: `<svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true"><circle cx="17" cy="17" r="12" fill="rgba(251,248,241,0.9)" stroke="${
      started ? '#D2560F' : '#1E5AA8'
    }" stroke-width="3"/><circle cx="17" cy="17" r="3.2" fill="${started ? '#D2560F' : '#1E5AA8'}"/><path d="M17 1v8M17 25v8M1 17h8M25 17h8" stroke="${started ? '#D2560F' : '#1E5AA8'}" stroke-width="2.4"/></svg>`,
  })
const HANDLE = { draft: handleIcon(false), started: handleIcon(true) }

const draftLabel = L.divIcon({
  className: 'leaflet-div-icon bare',
  iconSize: [0, 0],
  html: '<div class="attack-label draft">Test jammer, not started. Drag to move.</div>',
})

/** The jammer the judge is placing or editing: draggable centre + radius circle. */
export default function JammerEditor() {
  const tab = useStore((s) => s.tab)
  const jammer = useStore((s) => s.jammer)
  const setJammer = useStore((s) => s.setJammer)
  const toast = useStore((s) => s.toast)
  const d = useDerived()
  const attack = jammer.attackId ? d.attacks.find((a) => a.id === jammer.attackId) : null

  const handlers = useMemo(
    () => ({
      drag: (e) => {
        const p = e.target.getLatLng()
        setJammer({ center: [p.lat, p.lng] })
      },
      dragend: async (e) => {
        const p = e.target.getLatLng()
        const center = [+p.lat.toFixed(4), +p.lng.toFixed(4)]
        setJammer({ center })
        const id = useStore.getState().jammer.attackId
        if (id) {
          try {
            await api.patchAttack(id, { center })
            toast(`Moved ${id}. Detection restarts from the new position.`, 'ok')
          } catch (err) {
            toast(`Could not move the jammer: ${errorText(err)}`, 'error')
          }
        }
      },
    }),
    [setJammer, toast],
  )

  if (tab !== 'simulator' || !jammer.center) return null
  const started = Boolean(jammer.attackId)
  const style = !started ? DRAFT : attack?.live ? LIVE : OFF
  const labelPos = [jammer.center[0] - jammer.radius_km / 111.2, jammer.center[1]]

  return (
    <>
      <Pane name="jammer-edit" style={{ zIndex: 418 }}>
        <Circle center={jammer.center} radius={jammer.radius_km * 1000} pathOptions={style} />
      </Pane>
      <Pane name="jammer-label" style={{ zIndex: 627 }}>
        <Marker
          position={labelPos}
          icon={started ? attackLabelIcon(`${jammer.attackId}${attack && !attack.live ? ', switched off' : ''}`) : draftLabel}
          interactive={false}
          keyboard={false}
        />
      </Pane>
      <Marker position={jammer.center} draggable icon={started ? HANDLE.started : HANDLE.draft} eventHandlers={handlers} zIndexOffset={3000} title="Drag to move the jammer" />
    </>
  )
}
