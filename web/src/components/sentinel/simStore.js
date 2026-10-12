import { create } from 'zustand'
import { SIM_SATS } from '../../lib/satellites.js'

// Manual "Attack" mode of the Ground Sentinel. Same rules as backend/app/sentinel.py,
// run in the browser against dB values the judge sets by hand. Nothing is sent anywhere.
export const SIM_ID = 'manual-test'
const BASE = SIM_SATS.map((s) => s.base)
export const SIM_BASELINE = Math.round((BASE.reduce((a, b) => a + b, 0) / BASE.length) * 10) / 10
export const JAM_SNR_DB = 22 // backend config.sentinel_jam_snr_db: average signal below this reads as JAMMING
export const JAM_HOLD_S = 6 // backend config.sentinel_jam_hold_s: ...for this many seconds in a row
export const MIN_TRACK_DB = 20 // below this a receiver cannot track a satellite (assumption)
export const MIN_FOR_FIX = 4 // a position fix needs at least 4 satellites
const KEEP = 400

export const baseValues = () => BASE.slice()

export const useSim = create((set, get) => ({
  values: baseValues(),
  history: [],
  lastTs: null,
  lowSince: null, // when the average first went below the jam level (the hold timer)

  setValue: (i, v) => set((s) => ({ values: s.values.map((x, j) => (j === i ? v : x)) })),
  setDrop: (db) => set({ values: BASE.map((b) => Math.max(0, b - db)) }),
  reset: () => set({ values: baseValues() }),

  /** Evaluate the current values once; called every second while the tab is open. */
  tick: (now) => {
    const s = get()
    const used = s.values.filter((v) => v >= MIN_TRACK_DB)
    const fix = used.length >= MIN_FOR_FIX
    // Average over every satellite in view (like the box's avg_snr), so a covered antenna reads near 0.
    const avg = s.values.length ? Math.round((s.values.reduce((a, b) => a + b, 0) / s.values.length) * 10) / 10 : null
    const low = avg != null && avg < JAM_SNR_DB
    const lowSince = low ? (s.lowSince ?? now) : null // back at or above the level: timer resets at once
    let status = 'OK'
    let reason = fix ? null : 'no fix, signal normal'
    if (low) {
      const why = `signal ${avg.toFixed(1)} dB-Hz, below ${JAM_SNR_DB}`
      if (now - lowSince >= JAM_HOLD_S) {
        status = 'JAMMING'
        reason = why
      } else {
        reason = `${why}, confirming`
      }
    }
    const row = { recv_ts: now, avg_snr: avg, sats_used: used.length, fix, server_status: status, server_reason: reason }
    set({ history: [...s.history, row].slice(-KEEP), lastTs: now, lowSince })
  },
}))
