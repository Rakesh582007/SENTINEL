import L from 'leaflet'
import { memo, useMemo, useState } from 'react'
import { Marker, Pane, Polygon, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import { describePlace } from '../../data/places.js'
import { bearingDeg, haversineKm, ringToLatLngs } from '../../lib/geo.js'
import { stateOf } from '../../lib/states.js'
import { useDerived, useStore } from '../../store.js'

// H3 geometry never changes for a given id, so convert each ring once.
const latLngCache = new Map()
const latLngsOf = (id, ring) => {
  if (!latLngCache.has(id)) latLngCache.set(id, ringToLatLngs(ring))
  return latLngCache.get(id)
}

const styleCache = new Map()
function styleFor(state, selected) {
  const key = `${state}|${selected}`
  if (!styleCache.has(key)) {
    const s = stateOf(state)
    const alarm = state === 'jammed' || state === 'spoofing'
    styleCache.set(key, {
      color: selected ? '#143E73' : s.color,
      weight: selected ? 3.5 : alarm ? 2.2 : state === 'degraded' ? 1.8 : 1,
      opacity: state === 'insufficient' && !selected ? 0.55 : 0.95,
      dashArray: state === 'insufficient' && !selected ? '4 4' : null,
      fillColor: s.color,
      fillOpacity: s.fill,
    })
  }
  return styleCache.get(key)
}

export function cellSentence(c) {
  if (!c) return ''
  const s = stateOf(c.state)
  const n = `${c.n_aircraft} aircraft`
  if (c.state === 'insufficient') return `Too few aircraft to decide: ${n} seen`
  if (c.state === 'spoofing') return `${s.label}: physically impossible positions reported`
  return `${s.label}: ${c.n_bad} of ${n} reported bad GPS`
}

const CellPolygon = memo(function CellPolygon({ cell, selected, onPick }) {
  const handlers = useMemo(
    () => ({
      click: (e) => {
        L.DomEvent.stopPropagation(e)
        onPick(cell.id, e.latlng)
      },
    }),
    [cell.id, onPick],
  )
  return (
    <Polygon positions={latLngsOf(cell.id, cell.ring)} pathOptions={styleFor(cell.state, selected)} eventHandlers={handlers}>
      <Tooltip sticky className="st-tip" direction="top" offset={[0, -8]}>
        <span className="font-semibold">{describePlace(cell.center[0], cell.center[1], haversineKm, bearingDeg)?.text.replace(/^./, (x) => x.toUpperCase())}</span>
        <br />
        {cellSentence(cell)}. Click for details.
      </Tooltip>
    </Polygon>
  )
})

const labelCache = new Map()
function labelIcon(cell, injected) {
  const s = stateOf(cell.state)
  const count = cell.state === 'spoofing' ? '' : ` ${cell.n_bad}/${cell.n_aircraft}`
  const key = `${cell.state}|${count}|${injected}`
  if (!labelCache.has(key)) {
    labelCache.set(
      key,
      L.divIcon({
        className: 'leaflet-div-icon bare',
        iconSize: [0, 0],
        html: `<div class="map-label" style="color:${s.ink}"><span class="tag">${s.label.toUpperCase()}${count}${
          injected ? ' <span class="inj">INJECTED</span>' : ''
        }</span></div>`,
      }),
    )
  }
  return labelCache.get(key)
}

const PRIORITY = { jammed: 3, spoofing: 3, degraded: 1 }

/** Word labels on hexagons that need attention. Labels that would overlap a more
 *  important one are dropped until you zoom in (the tooltip still names the state). */
function CellLabels({ cells, injectedCells }) {
  const map = useMap()
  const [zoom, setZoom] = useState(map.getZoom())
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) })

  const placed = useMemo(() => {
    const boxes = []
    const keep = []
    const ranked = cells
      .filter((c) => PRIORITY[c.state])
      .sort((a, b) => PRIORITY[b.state] - PRIORITY[a.state] || b.n_bad - a.n_bad || b.n_aircraft - a.n_aircraft)
    for (const c of ranked) {
      const p = map.latLngToLayerPoint(c.center)
      const text = c.state === 'spoofing' ? 8 : 8 + String(c.n_bad).length + String(c.n_aircraft).length + 2
      const w = text * 7.4 + 12 + (injectedCells.has(c.id) ? 62 : 0)
      const box = { x0: p.x - w / 2 - 3, x1: p.x + w / 2 + 3, y0: p.y - 11, y1: p.y + 11 }
      if (boxes.some((b) => box.x0 < b.x1 && box.x1 > b.x0 && box.y0 < b.y1 && box.y1 > b.y0)) continue
      boxes.push(box)
      keep.push(c)
    }
    return keep
    // zoom is a dependency because layer points change with it
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cells, injectedCells, map, zoom])

  return (
    <Pane name="cell-labels" style={{ zIndex: 620 }}>
      {placed.map((c) => (
        <Marker key={c.id} position={c.center} icon={labelIcon(c, injectedCells.has(c.id))} interactive={false} keyboard={false} />
      ))}
    </Pane>
  )
}

/** Hexagons, filled by state, plus a word label on every hexagon that needs attention. */
export default function CellsLayer({ onCellClick }) {
  const d = useDerived()
  const selection = useStore((s) => s.selection)
  const showInsufficient = useStore((s) => s.showInsufficient)
  const selectedId = selection?.kind === 'cell' ? selection.id : null

  const cells = [...d.cellsById.values()].filter((c) => showInsufficient || c.state !== 'insufficient' || c.id === selectedId)
  // Draw quiet cells first so alarm outlines sit on top.
  const order = { insufficient: 0, clear: 1, degraded: 2, spoofing: 3, jammed: 3 }
  cells.sort((a, b) => (order[a.state] ?? 0) - (order[b.state] ?? 0))

  return (
    <>
      <Pane name="cells" style={{ zIndex: 400 }}>
        {cells.map((c) => (
          <CellPolygon key={c.id} cell={c} selected={c.id === selectedId} onPick={onCellClick} />
        ))}
      </Pane>
      <CellLabels cells={cells} injectedCells={d.injectedCells} />
    </>
  )
}
