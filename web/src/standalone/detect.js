// Browser copy of backend/app/detect/* and config.DetectionConfig, for the
// standalone build only. Same rules, same thresholds, same output shapes, so
// the UI behaves as it does against the real backend. If a rule changes in
// Python, change it here too (or regenerate the preview from the backend).
import { cellToBoundary, cellToLatLng, getHexagonEdgeLengthAvg, getResolution, gridDisk, latLngToCell, UNITS } from 'h3-js'
import { bearingDeg, destinationPoint, haversineKm } from '../lib/geo.js'

const KT_TO_KMH = 1.852

// ------------------------------------------------------------------ config.py DetectionConfig
export const DEFAULT_DETECTION = {
  h3_res: 3,
  jam_window_s: 1200,
  nacp_bad: 7,
  nic_bad: 5,
  min_aircraft: 3,
  jam_min_bad: 2,
  jam_lower_bound: 0.15,
  degraded_frac: 0.1,
  pos_loss_seen_max_s: 10.0,
  pos_loss_seen_pos_min_s: 60.0,
  gps_sourced_only: true,
  jump_speed_kt: 1000.0,
  jump_min_km: 5.0,
  jump_min_dt_s: 5.0,
  alt_peer_radius_km: 300.0,
  alt_peer_window_s: 600,
  alt_min_peers: 4,
  alt_abs_ft: 1000.0,
  alt_mad_k: 4.0,
  cluster_radius_km: 1.0,
  cluster_min_aircraft: 3,
  cluster_dt_s: 10.0,
  cluster_alt_spread_ft: 3000.0,
  track_mismatch_deg: 60.0,
  track_mismatch_min_gs_kt: 150.0,
  spoof_cell_min_flags: 2,
  warn_horizon_s: 900,
  warn_step_s: 30,
  incident_close_s: 600,
  jammer_radius_pct: 80.0,
  jammer_min_radius_km: 15.0,
  eval_detect_within_s: 300,
}

const RANGES = {
  h3_res: [2, 4, true],
  jam_window_s: [300, 1800, true],
  nacp_bad: [5, 9, true],
  nic_bad: [0, 8, true],
  min_aircraft: [2, 6, true],
  jam_min_bad: [1, 10, true],
  jam_lower_bound: [0, 1, false],
  degraded_frac: [0, 1, false],
  spoof_cell_min_flags: [1, 5, true],
}

/** Like pydantic: returns [config, null] or [null, FastAPI-style error list]. */
export function validateDetection(current, changes) {
  const errors = []
  const next = { ...current }
  for (const [k, v] of Object.entries(changes || {})) {
    if (!(k in DEFAULT_DETECTION)) {
      errors.push({ loc: ['body', k], msg: 'Extra inputs are not permitted', type: 'extra_forbidden' })
      continue
    }
    const r = RANGES[k]
    if (typeof DEFAULT_DETECTION[k] === 'boolean') {
      next[k] = Boolean(v)
      continue
    }
    if (typeof v !== 'number' || !Number.isFinite(v)) {
      errors.push({ loc: ['body', k], msg: 'Input should be a valid number', type: 'number_type' })
      continue
    }
    if (r && r[2] && !Number.isInteger(v)) {
      errors.push({ loc: ['body', k], msg: 'Input should be a valid integer', type: 'int_type' })
      continue
    }
    if (r && v < r[0]) errors.push({ loc: ['body', k], msg: `Input should be greater than or equal to ${r[0]}`, type: 'greater_than_equal' })
    else if (r && v > r[1]) errors.push({ loc: ['body', k], msg: `Input should be less than or equal to ${r[1]}`, type: 'less_than_equal' })
    else next[k] = v
  }
  return errors.length ? [null, errors] : [next, null]
}

// ------------------------------------------------------------------ records.py helpers
const GPS_SOURCED_TYPES = new Set(['adsb_icao', 'adsb_other'])
export const hasPosition = (r) => r.lat != null && r.lon != null
export const bestPosition = (r) => (hasPosition(r) ? [r.lat, r.lon] : r.last_lat != null && r.last_lon != null ? [r.last_lat, r.last_lon] : null)
export const gpsSourced = (r) => r.src_type == null || GPS_SOURCED_TYPES.has(r.src_type)

// ------------------------------------------------------------------ stats.py
export function wilsonLowerBound(k, n, z = 1.96) {
  if (n <= 0) return 0
  const p = k / n
  const z2 = z * z
  const denom = 1 + z2 / n
  const centre = p + z2 / (2 * n)
  const margin = z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))
  return Math.max(0, (centre - margin) / denom)
}

const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
}

export function medianMad(values) {
  if (!values.length) return [NaN, NaN]
  const med = median(values)
  return [med, median(values.map((v) => Math.abs(v - med)))]
}

export function percentile(values, pct) {
  if (!values.length) return NaN
  const xs = [...values].sort((a, b) => a - b)
  if (xs.length === 1) return xs[0]
  const pos = ((xs.length - 1) * pct) / 100
  const lo = Math.floor(pos)
  const hi = Math.min(lo + 1, xs.length - 1)
  return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
}

// ------------------------------------------------------------------ geo.py extras
export const angleDiffDeg = (a, b) => {
  const d = Math.abs(a - b) % 360
  return d > 180 ? 360 - d : d
}
const impliedSpeedKt = (km, dt) => (dt <= 0 ? Infinity : km / (dt / 3600) / KT_TO_KMH)

// ------------------------------------------------------------------ jamming.py
const eligible = (r, cfg) => !r.on_ground && (gpsSourced(r) || !cfg.gps_sourced_only)

export function badReason(r, cfg) {
  if (r.gps_ok_before != null) return 'gps_lost_flag'
  if (r.lat == null && r.last_lat != null && r.seen != null && r.seen <= cfg.pos_loss_seen_max_s && r.seen_pos != null && r.seen_pos >= cfg.pos_loss_seen_pos_min_s)
    return 'position_lost'
  if (r.nac_p != null && r.nac_p <= cfg.nacp_bad) return 'low_nacp'
  if (r.nic != null && r.nic <= cfg.nic_bad) return 'low_nic'
  return null
}

export function classifyState(n, k, frac, lb, cfg) {
  if (n < cfg.min_aircraft) return 'insufficient'
  if (k >= cfg.jam_min_bad && lb >= cfg.jam_lower_bound) return 'jammed'
  if (k >= 1 && frac >= cfg.degraded_frac) return 'degraded'
  return 'clear'
}

export function cellOf(r, res) {
  const p = bestPosition(r)
  return p ? latLngToCell(p[0], p[1], res) : null
}

export function classifyCells(records, cfg) {
  const seen = new Map()
  const bad = new Map()
  const injected = new Map()
  for (const r of records) {
    if (!eligible(r, cfg)) continue
    const cell = cellOf(r, cfg.h3_res)
    if (!cell) continue
    if (!seen.has(cell)) seen.set(cell, new Set())
    seen.get(cell).add(r.hex)
    const reason = badReason(r, cfg)
    if (reason) {
      if (!bad.has(cell)) bad.set(cell, new Map())
      const m = bad.get(cell)
      if (!m.has(r.hex)) m.set(r.hex, reason)
      if (r.injected) {
        if (!injected.has(cell)) injected.set(cell, new Set())
        injected.get(cell).add(r.hex)
      }
    }
  }
  const out = new Map()
  for (const [cell, hexes] of seen) {
    const n = hexes.size
    const badHere = bad.get(cell) || new Map()
    const k = badHere.size
    const frac = k / n
    const lb = wilsonLowerBound(k, n)
    const reasons = {}
    for (const why of badHere.values()) reasons[why] = (reasons[why] || 0) + 1
    out.set(cell, {
      h3: cell,
      n_aircraft: n,
      n_bad: k,
      frac_bad: frac,
      lower_bound: lb,
      state: classifyState(n, k, frac, lb, cfg),
      n_injected: injected.get(cell)?.size || 0,
      bad_hexes: [...badHere.keys()].sort(),
      reasons,
    })
  }
  return out
}

const r3 = (x) => Math.round(x * 1000) / 1000
const r4 = (x) => Math.round(x * 10000) / 10000
const r5 = (x) => Math.round(x * 100000) / 100000

export function toGeoJSON(cells) {
  return {
    type: 'FeatureCollection',
    features: [...cells.values()].map((c) => {
      const ring = cellToBoundary(c.h3).map(([lat, lng]) => [r5(lng), r5(lat)])
      ring.push(ring[0])
      return {
        type: 'Feature',
        id: c.h3,
        geometry: { type: 'Polygon', coordinates: [ring] },
        properties: {
          h3: c.h3,
          state: c.state,
          n_aircraft: c.n_aircraft,
          n_bad: c.n_bad,
          frac_bad: r3(c.frac_bad),
          lower_bound: r3(c.lower_bound),
          n_injected: c.n_injected,
          reasons: c.reasons,
        },
      }
    }),
  }
}

// ------------------------------------------------------------------ spoofing.py
const MIN_ALT_FOR_OFFSET_FT = 5000
const TRACK_CHECK_MAX_DT_S = 20
const TRACK_CHECK_MIN_KM = 1
const CLUSTER_LOOKBACK_S = 120
export const STRONG_REASONS = new Set(['impossible_jump', 'colocation_cluster'])
export const SPOOF_REASONS = new Set(['impossible_jump', 'colocation_cluster', 'alt_offset_outlier', 'track_mismatch'])

const weakGps = (r, cfg) => (r.nic != null && r.nic <= cfg.nic_bad) || (r.nac_p != null && r.nac_p <= cfg.nacp_bad)
const usable = (r) => !r.on_ground && r.lat != null && r.lon != null

function tracksOf(records) {
  const byHex = new Map()
  for (const r of records) {
    if (!usable(r)) continue
    if (!byHex.has(r.hex)) byHex.set(r.hex, [])
    byHex.get(r.hex).push(r)
  }
  for (const [hex, rs] of byHex) {
    rs.sort((a, b) => a.ts - b.ts)
    const seen = new Set()
    const out = []
    for (const r of rs) {
      const key = `${r.lat},${r.lon}`
      if (!seen.has(key)) {
        seen.add(key)
        out.push(r)
      }
    }
    byHex.set(hex, out)
  }
  return byHex
}

const meanHeading = (a, b) => {
  const d = ((b - a + 540) % 360) - 180
  return (a + d / 2 + 360) % 360
}

const addFlag = (flags, hex, code) => {
  if (!flags.has(hex)) flags.set(hex, new Set())
  flags.get(hex).add(code)
}

function jumpAndTrack(tracks, cfg, flags) {
  for (const [hex, rs] of tracks) {
    let prev = null
    let mismatches = 0
    for (const r of rs) {
      if (!prev) {
        prev = r
        continue
      }
      const dt = r.ts - prev.ts
      if (dt < cfg.jump_min_dt_s) continue
      const d = haversineKm(prev.lat, prev.lon, r.lat, r.lon)
      if (d > cfg.jump_min_km && impliedSpeedKt(d, dt) > cfg.jump_speed_kt) {
        addFlag(flags, hex, weakGps(prev, cfg) || weakGps(r, cfg) ? 'recovery_jump' : 'impossible_jump')
      } else if (
        r.track != null &&
        prev.track != null &&
        r.gs != null &&
        r.gs > cfg.track_mismatch_min_gs_kt &&
        dt <= TRACK_CHECK_MAX_DT_S &&
        d >= TRACK_CHECK_MIN_KM &&
        angleDiffDeg(meanHeading(prev.track, r.track), bearingDeg(prev.lat, prev.lon, r.lat, r.lon)) > cfg.track_mismatch_deg
      ) {
        mismatches += 1
        if (mismatches >= 2) addFlag(flags, hex, 'track_mismatch')
      }
      prev = r
    }
  }
}

function altOffset(tracks, cfg, flags) {
  let newest = -Infinity
  for (const rs of tracks.values()) if (rs.length) newest = Math.max(newest, rs[rs.length - 1].ts)
  if (!Number.isFinite(newest)) return
  const recent = new Map()
  for (const [hex, rs] of tracks) {
    const picked = []
    for (let i = rs.length - 1; i >= 0; i--) {
      const r = rs[i]
      if (r.ts < newest - cfg.alt_peer_window_s || picked.length === 3) break
      if (r.alt_geom != null && r.alt_baro != null && r.alt_baro >= MIN_ALT_FOR_OFFSET_FT && gpsSourced(r)) picked.push(r)
    }
    if (picked.length) recent.set(hex, picked)
  }
  const latest = new Map([...recent].map(([h, rs]) => [h, rs[0]]))
  for (const [hex, r] of latest) {
    const peers = []
    for (const [other, p] of latest) {
      if (other !== hex && haversineKm(r.lat, r.lon, p.lat, p.lon) <= cfg.alt_peer_radius_km) peers.push(p.alt_geom / p.alt_baro - 1)
    }
    if (peers.length < cfg.alt_min_peers) continue
    const [med, mad] = medianMad(peers)
    const readings = recent.get(hex)
    let outliers = 0
    for (const x of readings) {
      if (Math.abs(x.alt_geom - x.alt_baro - med * x.alt_baro) > Math.max(cfg.alt_abs_ft, cfg.alt_mad_k * mad * x.alt_baro)) outliers += 1
    }
    if (outliers >= Math.min(2, readings.length)) addFlag(flags, hex, 'alt_offset_outlier')
  }
}

function clusters(tracks, cfg, flags) {
  let newest = -Infinity
  for (const rs of tracks.values()) if (rs.length) newest = Math.max(newest, rs[rs.length - 1].ts)
  if (!Number.isFinite(newest)) return
  const recent = []
  for (const rs of tracks.values()) for (const r of rs) if (r.ts >= newest - CLUSTER_LOOKBACK_S && r.alt_baro != null) recent.push(r)
  recent.sort((a, b) => a.ts - b.ts)
  for (let i = 0; i < recent.length; i++) {
    const a = recent[i]
    const group = new Map([[a.hex, a]])
    for (let j = i + 1; j < recent.length; j++) {
      const b = recent[j]
      if (b.ts - a.ts > cfg.cluster_dt_s) break
      if (!group.has(b.hex) && haversineKm(a.lat, a.lon, b.lat, b.lon) <= cfg.cluster_radius_km) group.set(b.hex, b)
    }
    if (group.size >= cfg.cluster_min_aircraft) {
      const alts = [...group.values()].map((r) => r.alt_baro)
      if (Math.max(...alts) - Math.min(...alts) > cfg.cluster_alt_spread_ft) for (const hex of group.keys()) addFlag(flags, hex, 'colocation_cluster')
    }
  }
}

export function flagAircraft(records, cfg) {
  const tracks = tracksOf(records)
  const flags = new Map()
  jumpAndTrack(tracks, cfg, flags)
  altOffset(tracks, cfg, flags)
  clusters(tracks, cfg, flags)
  const out = new Map()
  for (const [hex, set] of flags) if (set.size) out.set(hex, [...set].sort())
  return out
}

export function spoofedCells(flags, records, cfg) {
  const spoofed = new Set([...flags].filter(([, reasons]) => reasons.some((c) => SPOOF_REASONS.has(c))).map(([h]) => h))
  if (!spoofed.size) return new Map()
  const newest = new Map()
  for (const r of records) {
    if (spoofed.has(r.hex) && usable(r) && (!newest.has(r.hex) || r.ts > newest.get(r.hex).ts)) newest.set(r.hex, r)
  }
  const strong = new Map()
  const weak = new Map()
  for (const r of newest.values()) {
    const cell = cellOf(r, cfg.h3_res)
    if (!cell) continue
    const target = flags.get(r.hex).some((c) => STRONG_REASONS.has(c)) ? strong : weak
    target.set(cell, (target.get(cell) || 0) + 1)
  }
  const out = new Map()
  for (const cell of new Set([...strong.keys(), ...weak.keys()])) {
    const s = strong.get(cell) || 0
    const w = weak.get(cell) || 0
    if (s >= 1 || w >= cfg.spoof_cell_min_flags) out.set(cell, s + w)
  }
  return out
}

// ------------------------------------------------------------------ warning.py
const MIN_GS_KT = 60

export function earlyWarnings(latest, alarmCells, cfg, now, injectedCells = new Set()) {
  if (!alarmCells.size) return []
  const res = getResolution(alarmCells.keys().next().value)
  const alerts = []
  for (const r of latest.values()) {
    if (r.on_ground || !hasPosition(r) || r.gs == null || r.track == null || r.gs < MIN_GS_KT) continue
    if (alarmCells.has(latLngToCell(r.lat, r.lon, res))) continue
    const age = Math.max(0, now - r.ts)
    const path = [[r4(r.lat), r4(r.lon)]]
    for (let t = cfg.warn_step_s; t <= cfg.warn_horizon_s; t += cfg.warn_step_s) {
      const [lat, lon] = destinationPoint(r.lat, r.lon, r.track, (r.gs * KT_TO_KMH * t) / 3600)
      path.push([r4(lat), r4(lon)])
      const cell = latLngToCell(lat, lon, res)
      if (!alarmCells.has(cell)) continue
      const eta = Math.max(0, t - age)
      const state = alarmCells.get(cell)
      const what = state === 'jammed' ? 'a GPS-jammed area' : 'an area with suspected GPS spoofing'
      const name = r.flight || r.hex.toUpperCase()
      alerts.push({
        id: `ew-${r.hex}-${cell}`,
        kind: 'early_warning',
        hex: r.hex,
        flight: r.flight,
        h3: cell,
        cell_state: state,
        eta_s: Math.round(eta),
        entry: [r4(lat), r4(lon)],
        path,
        injected: injectedCells.has(cell),
        severity: eta <= 300 ? 'high' : 'medium',
        message: `${name} enters ${what} in ~${Math.max(1, Math.round(eta / 60))} min. Prepare backup navigation.`,
      })
      break
    }
  }
  alerts.sort((a, b) => a.eta_s - b.eta_s)
  return alerts
}

// ------------------------------------------------------------------ incidents.py
const KIND_OF_STATE = { jammed: 'jamming', spoofing: 'spoofing' }

export class IncidentTracker {
  constructor() {
    this.incidents = new Map()
    this.seq = 1
  }

  update(cells, records, cfg, now, spoofFlags = new Map()) {
    const changed = new Set()
    for (const [cell, stat] of cells) {
      const kind = KIND_OF_STATE[stat.state]
      if (!kind) continue
      let inc = this.findOpen(cell, kind)
      if (!inc) inc = this.open(cell, kind, now)
      if (!inc.cells.includes(cell)) inc.cells.push(cell)
      inc.last_alarm_ts = now
      inc.max_frac_bad = Math.max(inc.max_frac_bad, r3(stat.frac_bad))
      inc.peak_aircraft = Math.max(inc.peak_aircraft, stat.n_aircraft)
      changed.add(inc.id)
    }
    if (changed.size) this.collectAircraft(records, cfg, spoofFlags, changed)
    for (const inc of this.incidents.values()) {
      if (inc.closed_ts == null && !changed.has(inc.id) && now - inc.last_alarm_ts > cfg.incident_close_s) {
        inc.closed_ts = now
        changed.add(inc.id)
      }
      if (changed.has(inc.id) && inc.kind === 'jamming') this.estimateArea(inc, cfg)
    }
  }

  findOpen(cell, kind) {
    const near = new Set(gridDisk(cell, 1))
    for (const inc of this.incidents.values()) if (inc.closed_ts == null && inc.kind === kind && inc.cells.some((c) => near.has(c))) return inc
    return null
  }

  open(cell, kind, now) {
    const id = `inc-${this.seq++}`
    const inc = {
      id,
      kind,
      opened_ts: now,
      closed_ts: null,
      last_alarm_ts: now,
      cells: [cell],
      aircraft: new Map(),
      max_frac_bad: 0,
      peak_aircraft: 0,
      est_lat: null,
      est_lon: null,
      est_radius_km: null,
    }
    this.incidents.set(id, inc)
    return inc
  }

  collectAircraft(records, cfg, spoofFlags, ids) {
    const open = [...ids].map((i) => this.incidents.get(i))
    const injectedByHex = new Map()
    for (const r of records) if (r.injected) injectedByHex.set(r.hex, r.injected)
    const sorted = [...records].sort((a, b) => a.ts - b.ts)
    for (const r of sorted) {
      const cell = cellOf(r, cfg.h3_res)
      if (!cell) continue
      for (const inc of open) {
        if (!inc.cells.includes(cell) || inc.aircraft.has(r.hex)) continue
        let why
        if (inc.kind === 'jamming') why = badReason(r, cfg)
        else {
          const reasons = spoofFlags.get(r.hex)
          why = reasons ? reasons.join(',') : null
        }
        if (!why) continue
        const pos = bestPosition(r)
        inc.aircraft.set(r.hex, {
          hex: r.hex,
          flight: r.flight,
          first_bad_ts: r.ts,
          reason: why,
          first_bad_pos: pos ? [r4(pos[0]), r4(pos[1])] : null,
          last_good_pos: r.gps_ok_lat != null ? [r.gps_ok_lat, r.gps_ok_lon] : null,
          alt_baro: r.alt_baro,
          injected: r.injected || injectedByHex.get(r.hex) || null,
        })
      }
    }
  }

  estimateArea(inc, cfg) {
    let pts = [...inc.aircraft.values()].map((a) => a.last_good_pos || a.first_bad_pos).filter((p) => p && p[0] != null)
    if (!pts.length) pts = inc.cells.map((c) => cellToLatLng(c))
    const lat = pts.reduce((s, p) => s + p[0], 0) / pts.length
    const lon = pts.reduce((s, p) => s + p[1], 0) / pts.length
    const dists = pts.map((p) => haversineKm(lat, lon, p[0], p[1]))
    const radius = Math.max(cfg.jammer_min_radius_km, dists.length > 1 ? percentile(dists, cfg.jammer_radius_pct) : 0)
    inc.est_lat = r4(lat)
    inc.est_lon = r4(lon)
    inc.est_radius_km = Math.round(radius * 10) / 10
  }

  static injected(inc) {
    const ac = [...inc.aircraft.values()]
    return ac.length > 0 && ac.every((a) => a.injected)
  }

  view(inc, full) {
    const { aircraft, ...rest } = inc
    const out = { ...rest, cells: [...inc.cells], n_aircraft: aircraft.size, injected: IncidentTracker.injected(inc), open: inc.closed_ts == null }
    if (full) out.aircraft = [...aircraft.values()].sort((a, b) => a.first_bad_ts - b.first_bad_ts)
    return out
  }

  summary() {
    return [...this.incidents.values()].sort((a, b) => b.opened_ts - a.opened_ts).map((i) => this.view(i, false))
  }

  get(id) {
    const inc = this.incidents.get(id)
    return inc ? this.view(inc, true) : null
  }

  reset() {
    this.incidents.clear()
  }
}

// ------------------------------------------------------------------ evaluate.py
const SLACK_S = 15

function cellOverlaps(cell, center, radiusKm) {
  const [lat, lon] = cellToLatLng(cell)
  const edge = getHexagonEdgeLengthAvg(getResolution(cell), UNITS.km)
  return haversineKm(lat, lon, center[0], center[1]) <= radiusKm + edge
}

export function evaluate(groundTruth, detections, cfg, now, coverage, flagLog = []) {
  const perEvent = []
  const used = new Set()
  for (const ev of groundTruth) {
    const start = ev.start_ts
    const windowEnd = start + cfg.eval_detect_within_s
    let hit = null
    if (ev.kind === 'jamming') {
      for (let i = 0; i < detections.length; i++) {
        const d = detections[i]
        if (d.state === 'jammed' && start - SLACK_S <= d.ts && d.ts <= windowEnd && cellOverlaps(d.h3, ev.center, ev.radius_km)) {
          hit = d
          used.add(i)
          break
        }
      }
    } else {
      for (const f of flagLog) {
        if (f.hex === ev.hex && start - SLACK_S <= f.ts && f.ts <= windowEnd && f.reasons.some((c) => SPOOF_REASONS.has(c))) {
          hit = f
          break
        }
      }
      detections.forEach((d, i) => {
        if (d.state === 'spoofing' && start - SLACK_S <= d.ts && d.ts <= windowEnd) used.add(i)
      })
    }
    let outcome
    let ttd = null
    if (hit) {
      outcome = 'detected'
      ttd = Math.max(0, hit.ts - start)
    } else if (now < windowEnd) outcome = 'pending'
    else if (ev.kind === 'jamming' && (coverage[ev.attack_id] || 0) < cfg.min_aircraft) outcome = 'undetectable'
    else outcome = 'missed'
    perEvent.push({
      attack_id: ev.attack_id,
      kind: ev.kind,
      start_ts: start,
      end_ts: ev.end_ts,
      outcome,
      time_to_detect_s: ttd == null ? null : Math.round(ttd * 10) / 10,
      max_aircraft_inside: coverage[ev.attack_id] ?? null,
    })
  }
  const counts = { detected: 0, missed: 0, undetectable: 0, pending: 0 }
  for (const e of perEvent) counts[e.outcome] += 1
  const unexplained = detections.filter((_, i) => !used.has(i))
  const ttds = perEvent.map((e) => e.time_to_detect_s).filter((v) => v != null)
  const scored = counts.detected + counts.missed
  return {
    events: perEvent.length,
    ...counts,
    detection_rate: scored ? Math.round((counts.detected / scored) * 1000) / 1000 : null,
    unexplained_alarms: unexplained.length,
    unexplained_real_data: unexplained.filter((d) => !d.n_injected).length,
    median_time_to_detect_s: ttds.length ? Math.round(median(ttds) * 10) / 10 : null,
    per_event: perEvent,
    note: 'Unexplained alarms on live data may be real interference; they are not counted as false alarms.',
  }
}
