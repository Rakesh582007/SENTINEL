import { CircleMarker, Pane, Polyline, Tooltip } from 'react-leaflet'
import { stateOf } from '../../lib/states.js'
import { useDerived } from '../../store.js'

const pathStyle = {}
const styleFor = (state) => {
  if (!pathStyle[state]) {
    const c = stateOf(state).color
    pathStyle[state] = {
      line: { color: c, weight: 2.4, opacity: 0.95, dashArray: '7 6', lineCap: 'round' },
      entry: { color: c, weight: 2.4, fillColor: '#FBF8F1', fillOpacity: 1 },
    }
  }
  return pathStyle[state]
}

/** Projected straight-line paths of aircraft heading into a jammed or spoofed hexagon. */
export default function WarningPaths() {
  const d = useDerived()
  const warnings = d.alerts.filter((a) => a.kind === 'early_warning' && Array.isArray(a.path) && a.path.length > 1)
  return (
    <Pane name="warnings" style={{ zIndex: 445 }}>
      {warnings.map((a) => {
        const st = styleFor(a.cell_state)
        return (
          <Polyline key={a.id} positions={a.path} pathOptions={st.line}>
            <Tooltip sticky className="st-tip">
              {a.message}
            </Tooltip>
          </Polyline>
        )
      })}
      {warnings.map((a) =>
        a.entry ? (
          <CircleMarker key={`${a.id}-entry`} center={a.entry} radius={5} pathOptions={styleFor(a.cell_state).entry}>
            <Tooltip className="st-tip" direction="top" offset={[0, -6]}>
              {(a.flight || a.hex?.toUpperCase()) ?? 'Aircraft'} enters here
            </Tooltip>
          </CircleMarker>
        ) : null,
      )}
    </Pane>
  )
}
