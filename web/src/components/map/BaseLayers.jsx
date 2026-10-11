import L from 'leaflet'
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { GeoJSON, Marker, Pane, Polyline, TileLayer, useMap, useMapEvents } from 'react-leaflet'
import { AIRPORTS } from '../../data/airports.js'
import southAsia from '../../data/south-asia.json'
import { useStore } from '../../store.js'

// The default base map is drawn from our own vector outline, so it works with
// no internet (venue Wi-Fi) and shows India's boundary as India's official
// map does (Natural Earth, India point of view: all of J&K and Ladakh).
// Street tiles are optional and use the tile provider's own boundaries.

const outlineStyle = (tiles) => (feature) => {
  const india = feature.properties.iso === 'IND'
  return {
    stroke: true,
    color: india ? '#7A6A47' : '#B9AA86',
    weight: india ? 1.3 : 0.8,
    opacity: tiles ? 0.9 : 1,
    fill: !tiles,
    fillColor: india ? '#ECE3CD' : '#F4EEE0',
    fillOpacity: tiles ? 0 : 1,
    interactive: false,
  }
}

function Outline() {
  const basemap = useStore((s) => s.basemap)
  const tiles = basemap === 'tiles'
  const style = useMemo(() => outlineStyle(tiles), [tiles])
  return <GeoJSON key={basemap} data={southAsia} style={style} interactive={false} />
}

function Tiles() {
  const basemap = useStore((s) => s.basemap)
  const toast = useStore((s) => s.toast)
  const warned = useRef(false)
  if (basemap !== 'tiles') return null
  return (
    <TileLayer
      url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
      subdomains="abcd"
      maxZoom={12}
      eventHandlers={{
        tileerror: () => {
          if (!warned.current) {
            warned.current = true
            toast('Street tiles are not loading (no internet?). The chart outline still shows everything.', 'error')
          }
        },
      }}
    />
  )
}

const aptIcons = new Map()
function airportIcon(icao, city, zoom) {
  const showCity = zoom >= 6
  const key = `${icao}|${showCity}`
  if (!aptIcons.has(key)) {
    aptIcons.set(
      key,
      L.divIcon({
        className: 'leaflet-div-icon bare',
        iconSize: [0, 0],
        html: `<div class="apt"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="3.6" fill="#FBF8F1" stroke="#1E5AA8" stroke-width="1.5"/><path d="M7 0.6v2.2M7 11.2v2.2M0.6 7h2.2M11.2 7h2.2" stroke="#1E5AA8" stroke-width="1.4"/></svg><span class="name">${icao}${showCity ? ` ${city}` : ''}</span></div>`,
      }),
    )
  }
  return aptIcons.get(key)
}

function Airports() {
  const map = useMap()
  const [zoom, setZoom] = useState(map.getZoom())
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) })
  if (zoom < 5) return null
  return (
    <Pane name="airports" style={{ zIndex: 430 }}>
      {AIRPORTS.map((a) => (
        <Marker key={a.icao} position={[a.lat, a.lon]} icon={airportIcon(a.icao, a.city, zoom)} interactive={false} keyboard={false} />
      ))}
    </Pane>
  )
}

const STEP_BY_ZOOM = (z) => (z <= 4 ? 10 : z === 5 ? 5 : z === 6 ? 2 : z === 7 ? 1 : 0.5)

function Graticule() {
  const map = useMap()
  const [view, setView] = useState(() => ({ bounds: map.getBounds(), zoom: map.getZoom(), v: 0 }))
  const raf = useRef(0)
  const update = () => {
    cancelAnimationFrame(raf.current)
    raf.current = requestAnimationFrame(() => setView((s) => ({ bounds: map.getBounds(), zoom: map.getZoom(), v: s.v + 1 })))
  }
  useMapEvents({ move: update, zoomend: update, resize: update })
  useEffect(() => () => cancelAnimationFrame(raf.current), [])

  const step = STEP_BY_ZOOM(view.zoom)
  const b = view.bounds
  const lons = []
  const lats = []
  for (let lon = Math.ceil(b.getWest() / step) * step; lon <= b.getEast(); lon += step) lons.push(+lon.toFixed(2))
  for (let lat = Math.ceil(b.getSouth() / step) * step; lat <= b.getNorth(); lat += step) lats.push(+lat.toFixed(2))
  const south = Math.max(-85, b.getSouth() - 5)
  const north = Math.min(85, b.getNorth() + 5)
  const west = b.getWest() - 5
  const east = b.getEast() + 5
  const style = { color: '#A7C6E2', weight: 1, opacity: 0.75, interactive: false }
  const center = b.getCenter()
  const fmt = (v, pos, neg) => `${Math.abs(v)}°${v >= 0 ? pos : neg}`

  return (
    <>
      <Pane name="graticule" style={{ zIndex: 250 }}>
        {lons.map((lon) => (
          <Polyline key={`m${lon}`} positions={[[south, lon], [north, lon]]} pathOptions={style} />
        ))}
        {lats.map((lat) => (
          <Polyline key={`p${lat}`} positions={[[lat, west], [lat, east]]} pathOptions={style} />
        ))}
      </Pane>
      {createPortal(
        <div className="pointer-events-none absolute inset-0" style={{ zIndex: 640 }} aria-hidden="true">
          {lons.map((lon) => {
            const x = map.latLngToContainerPoint([center.lat, lon]).x
            return x > 30 && x < map.getSize().x - 60 ? (
              <span key={`ml${lon}`} className="graticule-label" style={{ left: x, top: 5 }}>
                {fmt(lon, 'E', 'W')}
              </span>
            ) : null
          })}
          {lats.map((lat) => {
            const y = map.latLngToContainerPoint([lat, center.lng]).y
            return y > 24 && y < map.getSize().y - 40 ? (
              <span key={`pl${lat}`} className="graticule-label left" style={{ left: 5, top: y }}>
                {fmt(lat, 'N', 'S')}
              </span>
            ) : null
          })}
        </div>,
        map.getContainer(),
      )}
    </>
  )
}

export default function BaseLayers() {
  return (
    <>
      <Pane name="base" style={{ zIndex: 150 }}>
        <Tiles />
      </Pane>
      <Pane name="outline" style={{ zIndex: 200 }}>
        <Outline />
      </Pane>
      <Graticule />
      <Airports />
    </>
  )
}
