import { useStore } from '../../store.js'
import AlertsPanel from '../panels/AlertsPanel.jsx'
import IncidentsPanel from '../panels/IncidentsPanel.jsx'
import ActiveAttacks from './ActiveAttacks.jsx'
import JammingControls from './JammingControls.jsx'
import ScenarioRunner from './ScenarioRunner.jsx'
import SensitivityPanel from './SensitivityPanel.jsx'
import SpoofControls from './SpoofControls.jsx'

/** Side panel of the Attack simulator tab (handover §6.2). */
export default function SimulatorPanel() {
  const tick = useStore((s) => s.tick)
  return (
    <div className="space-y-6 p-4">
      <div className="rounded-lg border-2 border-signal-500 bg-signal-50 px-3 py-2.5" role="note">
        <p className="text-[16px] font-bold leading-snug text-signal-900">Attacks are simulated data only. Nothing is transmitted.</p>
        <p className="mt-0.5 text-[13px] leading-snug text-signal-900">
          They alter copies of aircraft reports before detection, and everything they touch is marked INJECTED TEST ATTACK.
          {tick?.mode === 'replay' ? ' Keep the replay playing: attacks act on data that arrives after them.' : ''}
        </p>
      </div>
      <JammingControls />
      <SpoofControls />
      <ActiveAttacks />
      <AlertsPanel title="Aircraft to notify" simulator />
      <IncidentsPanel title="Test incidents and reports" />
      <SensitivityPanel />
      <ScenarioRunner />
    </div>
  )
}
