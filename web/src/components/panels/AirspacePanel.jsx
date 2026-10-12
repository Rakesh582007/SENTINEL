import { useStore } from '../../store.js'
import AlertsPanel from './AlertsPanel.jsx'
import CellDetail from './CellDetail.jsx'
import IncidentsPanel from './IncidentsPanel.jsx'

/** Side panel of the Live airspace tab: warnings and incidents, or one hexagon's details. */
export default function AirspacePanel() {
  const selection = useStore((s) => s.selection)
  if (selection?.kind === 'cell') {
    return (
      <div className="p-4">
        <CellDetail id={selection.id} />
      </div>
    )
  }
  return (
    <div className="space-y-6 p-4">
      <AlertsPanel />
      <IncidentsPanel />
      <p className="text-[12.5px] leading-snug text-ink-600">Click any hexagon on the map to see where it is, what it means, its aircraft and a summary.</p>
    </div>
  )
}
