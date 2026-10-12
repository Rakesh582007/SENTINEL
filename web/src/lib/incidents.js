// Incident helpers shared by the incident list, the map chips and the replay timeline.
import { cellToLatLng } from 'h3-js'
import { api, errorText } from '../api/client.js'
import { describePlace } from '../data/places.js'
import { useStore } from '../store.js'
import { bearingDeg, haversineKm } from './geo.js'
import { istTime } from './time.js'

/** Seconds of recording to play before the incident opened, so you watch it start. */
export const LEAD_S = 90

/** "inc-r055546-11" -> "11" (the run id is for the database, not for people). */
export const incidentNumber = (inc) => String(inc?.id ?? '').split('-').pop()

export function incidentCentre(inc) {
  if (inc.est_lat != null && inc.est_lon != null) return [inc.est_lat, inc.est_lon]
  const h = inc.cells?.[0]
  if (!h) return null
  try {
    return cellToLatLng(h)
  } catch {
    return null
  }
}

/** "about 15 km south of Gurdaspur" (short form, no state name). */
export function incidentPlace(inc) {
  const c = incidentCentre(inc)
  if (!c) return null
  return describePlace(c[0], c[1], haversineKm, bearingDeg)
}

export function incidentBounds(inc, cellsById) {
  const pts = []
  for (const h of inc.cells || []) {
    const c = cellsById?.get(h)
    if (c) for (const [lon, lat] of c.ring) pts.push([lat, lon])
  }
  if (inc.est_lat != null && inc.est_radius_km) {
    const dLat = inc.est_radius_km / 111.2
    const dLon = dLat / Math.cos((inc.est_lat * Math.PI) / 180)
    pts.push([inc.est_lat - dLat, inc.est_lon - dLon], [inc.est_lat + dLat, inc.est_lon + dLon])
  }
  if (!pts.length) {
    const c = incidentCentre(inc)
    if (!c) return null
    pts.push([c[0] - 0.6, c[1] - 0.6], [c[0] + 0.6, c[1] + 0.6])
  }
  const lats = pts.map((p) => p[0])
  const lons = pts.map((p) => p[1])
  return [
    [Math.min(...lats), Math.min(...lons)],
    [Math.max(...lats), Math.max(...lons)],
  ]
}

/**
 * Click on an incident: zoom to it and play the recording from just before it opened.
 * In replay mode that is a seek. In live mode the backend switches to replay (the live
 * poller records what it fetched, so recent incidents are in the recordings).
 */
export async function replayIncident(inc, cellsById) {
  const st = useStore.getState()
  const tick = st.tick
  const bounds = incidentBounds(inc, cellsById)
  if (bounds) st.focusOn({ bounds, maxZoom: 8 })
  const place = incidentPlace(inc)
  const target = inc.opened_ts - LEAD_S
  const focus = { id: inc.id, num: incidentNumber(inc), kind: inc.kind, opened_ts: inc.opened_ts, place: place?.short || null, bounds }

  try {
    if (tick?.mode === 'replay' && tick.replay) {
      const r = tick.replay
      if (inc.opened_ts < r.t_start - 1 || inc.opened_ts > r.t_end + 1) {
        st.toast('That incident is outside the recording that is loaded, so it cannot be replayed here.', 'error')
        return
      }
      st.setReplayFocus(focus)
      await api.seek(Math.max(r.t_start, target))
      if (r.paused) {
        st.setReplayOverride({ paused: false })
        await api.play()
      }
      st.toast(`Replaying incident #${focus.num} from ${istTime(Math.max(r.t_start, target))} IST.`, 'ok')
    } else {
      st.setReplayFocus(focus)
      await api.setMode('replay', { start_ts: target })
      st.toast(`Switched to the recording at ${istTime(target)} IST to replay incident #${focus.num}. Use Live to go back.`, 'ok')
    }
  } catch (e) {
    st.setReplayFocus(null)
    st.toast(`Could not replay the incident: ${errorText(e)}`, 'error')
  }
}
