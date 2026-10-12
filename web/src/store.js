import { create } from 'zustand'
import { hasSpoofEvidence } from './lib/states.js'
import { pointInRing, ringCenter } from './lib/geo.js'

let toastSeq = 0
let focusSeq = 0

export const useStore = create((set, get) => ({
  // ---------------------------------------------------------------- live feed
  tick: null,
  tickRecvAt: 0, // performance.now() when the tick arrived (drives countdowns between ticks)
  connection: { state: 'connecting', attempt: 0, retryAt: null },
  setTick: (tick) =>
    set((s) => {
      // Drop an optimistic replay setting once the backend's tick agrees with it.
      let replayOverride = s.replayOverride
      const r = tick?.replay
      if (replayOverride && r && (replayOverride.speed == null || r.speed === replayOverride.speed) && (replayOverride.paused == null || r.paused === replayOverride.paused))
        replayOverride = null
      return { tick, tickRecvAt: performance.now(), replayOverride }
    }),
  // Speed / pause the user just clicked, shown at once instead of waiting up to 5 s for the next tick.
  replayOverride: null,
  setReplayOverride: (patch) => set((s) => ({ replayOverride: patch ? { ...(s.replayOverride || {}), ...patch } : null })),
  setConnection: (connection) => set({ connection }),

  // ---------------------------------------------------------------- navigation
  tab: 'home', // home | airspace | simulator | sentinel
  setTab: (tab) => set({ tab, picking: false }),
  selection: null, // { kind: 'cell' | 'aircraft', id }
  select: (kind, id) => set({ selection: kind && id ? { kind, id } : null }),
  clearSelection: () => set({ selection: null }),

  // The incident being replayed (set by lib/incidents.replayIncident): drives the map banner
  // and the highlight. {id, num, kind, opened_ts, place, bounds} | null
  replayFocus: null,
  setReplayFocus: (replayFocus) => set({ replayFocus }),

  // Ask the map to move. { center, zoom } or { bounds: [[lat, lon], [lat, lon]] }
  focus: null,
  focusOn: (target) => set({ focus: { ...target, seq: ++focusSeq } }),

  // ---------------------------------------------------------------- map options
  showInsufficient: false, // grey 'too few aircraft' hexagons are noise on a projector; legend toggle shows them
  toggleInsufficient: () => set((s) => ({ showInsufficient: !s.showInsufficient })),
  basemap: 'outline', // outline | tiles
  setBasemap: (basemap) => set({ basemap }),

  // Current detection thresholds (GET /api/config/detection); refreshed by the sensitivity panel.
  detection: null,
  setDetection: (detection) => set({ detection }),

  evaluationOpen: false,
  setEvaluationOpen: (evaluationOpen) => set({ evaluationOpen }),

  // ---------------------------------------------------------------- toasts
  toasts: [],
  toast: (text, tone = 'info') => {
    const id = ++toastSeq
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, text, tone }] }))
    window.setTimeout(() => get().dismissToast(id), tone === 'error' ? 7000 : 4000)
  },
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  // ---------------------------------------------------------------- attack simulator
  // The jammer being edited: a draft until started, then bound to attackId.
  // Defaults are stronger than the handover's 60 km / 70%: measured on the bundled sample, that
  // jammer left the busy Delhi hexagon amber for minutes, while 80 km / 80% turned it red in one tick.
  jammer: { center: null, radius_km: 80, strength: 0.8, position_loss: 0.3, duration_min: null, attackId: null },
  setJammer: (patch) => set((s) => ({ jammer: { ...s.jammer, ...patch } })),
  resetJammer: () =>
    set((s) => ({ jammer: { ...s.jammer, center: null, attackId: null }, jammerPreview: null })),
  jammerPreview: null, // GET /api/attacks/preview result for the jammer position
  setJammerPreview: (jammerPreview) => set({ jammerPreview }),

  spoof: { target: 'random', offset_km: 25, bearing_deg: 45, alt_offset_ft: 0, duration_min: 5 },
  setSpoof: (patch) => set((s) => ({ spoof: { ...s.spoof, ...patch } })),
  picking: false, // clicking an aircraft picks it as the spoof target
  setPicking: (picking) => set({ picking }),
}))

// ---------------------------------------------------------------- views
// The backend runs the detectors twice per tick: on everything (Attack Simulator: real traffic
// plus simulated attacks) and on real data only (tick.real). Live airspace and Home use the real
// view, so a judge's jammer never shows up there. Fields that are not per-view (mode, replay,
// sentinel, credits) are shared.
const realCache = new WeakMap()
export function viewTick(tick, view) {
  if (!tick || view === 'sim' || !tick.real) return tick
  let t = realCache.get(tick)
  if (!t) {
    t = { ...tick, ...tick.real, attacks: [], scenario: null, real: undefined, view: 'real' }
    realCache.set(tick, t)
  }
  return t
}
export const viewOfTab = (tab) => (tab === 'simulator' ? 'sim' : 'real')
export const useView = () => useStore((s) => viewOfTab(s.tab))
export const useViewTick = () => viewTick(useStore((s) => s.tick), useView())

// ---------------------------------------------------------------- derived data
// Computed once per (tick, view) and shared by every component.
const deriveCache = new WeakMap()

const EMPTY = {
  cells: [],
  cellsById: new Map(),
  aircraft: [],
  aircraftByHex: new Map(),
  aircraftInCell: new Map(),
  injectedCells: new Set(),
  incidentsByCell: new Map(),
  alerts: [],
  attacks: [],
  incidents: [],
}

export function derive(tick) {
  if (!tick) return EMPTY
  const hit = deriveCache.get(tick)
  if (hit) return hit
  const cells = tick.cells?.features || []
  const aircraft = tick.aircraft || []
  const cellsById = new Map()
  const aircraftByHex = new Map(aircraft.map((a) => [a.hex, a]))
  const aircraftInCell = new Map()

  for (const f of cells) {
    const ring = f.geometry?.coordinates?.[0] || []
    const inside = []
    for (const a of aircraft) {
      if (a.lat != null && a.lon != null && pointInRing(a.lat, a.lon, ring)) inside.push(a)
    }
    aircraftInCell.set(f.id, inside)
    cellsById.set(f.id, { ...f.properties, id: f.id, ring, center: ringCenter(ring) })
  }

  // A hexagon counts as injected when simulated attacks explain its badness.
  // n_injected covers jamming; for a purple cell we also look for a spoofed
  // aircraft that carries an attack id (the backend's n_injected only counts
  // jamming-style "bad GPS" aircraft).
  const injectedCells = new Set()
  for (const c of cellsById.values()) {
    if (c.n_injected > 0) injectedCells.add(c.id)
    else if (c.state === 'spoofing') {
      const inside = aircraftInCell.get(c.id) || []
      if (inside.some((a) => a.injected && hasSpoofEvidence(a.spoof))) injectedCells.add(c.id)
    }
  }

  const incidents = tick.incidents_summary || []
  const incidentsByCell = new Map()
  for (const inc of incidents) {
    for (const h of inc.cells || []) {
      const cur = incidentsByCell.get(h)
      if (!cur || (inc.open && !cur.open) || (inc.open === cur.open && inc.opened_ts > cur.opened_ts)) incidentsByCell.set(h, inc)
    }
  }

  const alerts = [...(tick.alerts || [])].sort((a, b) => {
    const sa = a.kind === 'early_warning' ? 1 : 0
    const sb = b.kind === 'early_warning' ? 1 : 0
    if (sa !== sb) return sa - sb // sentinel alarms first
    return (a.eta_s ?? 0) - (b.eta_s ?? 0)
  })

  const memo = {
    cells,
    cellsById,
    aircraft,
    aircraftByHex,
    aircraftInCell,
    injectedCells,
    incidentsByCell,
    alerts,
    attacks: tick.attacks || [],
    incidents,
  }
  deriveCache.set(tick, memo)
  return memo
}

export const useDerived = () => derive(useViewTick())

/** Is this alert caused by a simulated attack? */
export function alertInjected(alert, d) {
  return Boolean(alert.injected) || (alert.h3 ? d.injectedCells.has(alert.h3) : false)
}
