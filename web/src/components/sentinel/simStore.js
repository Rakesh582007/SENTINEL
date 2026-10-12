import { create } from 'zustand'
import { SIM_SATS } from '../../lib/satellites.js'

// Manual "Attack" mode of the Ground Sentinel. Same rules as backend/app/sentinel.py,
// run in the browser against dB values the judge sets by hand. Nothing is sent anywhere.
export const SIM_ID = 'manual-test'
const BASE = SIM_SATS.map((s) => s.base)
export const SIM_BASELINE = Math.round((BASE.reduce((a, b) => a + b, 0) / BASE.length) * 10) / 10
export const DROP_DB = 10 // sentinel.SNR_DROP_DB
export const FIX_LOSS_S = 5 // sentinel.FIX_LOSS_S
export const MIN_TRACK_DB = 20 // below this a receiver cannot track a satellite (assumption)
export const MIN_FOR_FIX = 4 // a position fix needs at least 4 satellites
const KEEP = 400

export const baseValues = () => BASE.slice()

export const useSim = create((set, get) => ({
  values: baseValues(),
  history: [],
  fixLostSince: null,
  lastTs: null,

  setValue: (i, v) => set((s) => ({ values: s.values.map((x, j) => (j === i ? v : x)) })),
  setDrop: (db) => set({ values: BASE.map((b) => Math.max(0, b - db)) }),
  reset: () => set({ values: baseValues() }),

  /** Evaluate the current values once; called every second while the tab is open. */
  tick: (now) => {
    const s = get()
    const used = s.values.filter((v) => v >= MIN_TRACK_DB)
    const fix = used.length >= MIN_FOR_FIX
    const avg = used.length ? Math.round((used.reduce((a, b) => a + b, 0) / used.length) * 10) / 10 : null
    let lostSince = s.fixLostSince
    if (s.lastTs != null && now - s.lastTs > FIX_LOSS_S) lostSince = null // the tab was closed for a while
    let status = 'OK'
    let reason = null
    if (!fix) {
      if (lostSince == null) lostSince = now
      if (now - lostSince > FIX_LOSS_S) {
        status = 'JAMMING'
        reason = `fix lost for ${Math.round(now - lostSince)} s`
      }
    } else {
      lostSince = null
      if (avg != null && avg <= SIM_BASELINE - DROP_DB) {
        status = 'JAMMING'
        reason = `signal ${Math.round(SIM_BASELINE - avg)} dB below baseline`
      }
    }
    const row = { recv_ts: now, avg_snr: avg, sats_used: used.length, fix, server_status: status, server_reason: reason }
    set({ history: [...s.history, row].slice(-KEEP), fixLostSince: lostSince, lastTs: now })
  },
}))
