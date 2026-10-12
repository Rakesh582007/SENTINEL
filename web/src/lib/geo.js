// Small geometry helpers. No H3 maths here: hexagons arrive as GeoJSON.
const R = 6371.0088
const rad = (d) => (d * Math.PI) / 180
const deg = (r) => (r * 180) / Math.PI

export function haversineKm(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1)
  const p2 = rad(lat2)
  const dp = p2 - p1
  const dl = rad(lon2 - lon1)
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)))
}

export function destinationPoint(lat, lon, bearingDeg, distKm) {
  const d = distKm / R
  const b = rad(bearingDeg)
  const p1 = rad(lat)
  const l1 = rad(lon)
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b))
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2))
  return [deg(p2), ((deg(l2) + 540) % 360) - 180]
}

export function bearingDeg(lat1, lon1, lat2, lon2) {
  const p1 = rad(lat1)
  const p2 = rad(lat2)
  const dl = rad(lon2 - lon1)
  const x = Math.sin(dl) * Math.cos(p2)
  const y = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl)
  return (deg(Math.atan2(x, y)) + 360) % 360
}

/** Ray casting on a GeoJSON ring of [lon, lat] pairs. */
export function pointInRing(lat, lon, ring) {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]
    const [xj, yj] = ring[j]
    if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

/** Centre of a GeoJSON ring as [lat, lon] (vertex mean; fine for hexagons). */
export function ringCenter(ring) {
  const pts = ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1] ? ring.slice(0, -1) : ring
  let lat = 0
  let lon = 0
  for (const [x, y] of pts) {
    lon += x
    lat += y
  }
  return [lat / pts.length, lon / pts.length]
}

/** Leaflet wants [lat, lon]; GeoJSON gives [lon, lat]. */
export const ringToLatLngs = (ring) => ring.map(([x, y]) => [y, x])

export function fmtLatLon(lat, lon) {
  if (lat == null || lon == null) return '–'
  const ns = lat >= 0 ? 'N' : 'S'
  const ew = lon >= 0 ? 'E' : 'W'
  return `${Math.abs(lat).toFixed(2)}°${ns} ${Math.abs(lon).toFixed(2)}°${ew}`
}
