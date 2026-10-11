// Browser copy of backend/app/runtime.py + state.py + ingest/injector.py +
// ingest/replay.py + sentinel.py, for the standalone build only. It replays
// the bundled real sample, injects simulated attacks exactly like the
// backend, and produces the same tick payload every 5 s.
import { latLngToCell } from 'h3-js'
import { destinationPoint, haversineKm } from '../lib/geo.js'
import {
  DEFAULT_DETECTION,
  IncidentTracker,
  SPOOF_REASONS,
  badReason,
  bestPosition,
  classifyCells,
  earlyWarnings,
  evaluate,
  flagAircraft,
  hasPosition,
  spoofedCells,
  toGeoJSON,
} from './detect.js'

const TICK_S = 5
const WINDOW_KEEP_S = 1800
const AIRCRAFT_MAX_AGE_S = 90
const GAP_S = 120
const LABEL = 'INJECTED TEST ATTACK'
export const ATTRIBUTION = { 'adsb.fi': 'https://adsb.fi', 'adsb.lol': 'https://adsb.lol', 'airplanes.live': 'https://airplanes.live' }

export const REGIONS = {
  nw_border: [
    { name: 'amritsar', lat: 31.6, lon: 74.9, radius_nm: 250 },
    { name: 'jk', lat: 33.6, lon: 75.0, radius_nm: 150 },
  ],
  delhi: [{ name: 'delhi', lat: 28.6, lon: 77.2, radius_nm: 150 }],
  north_india: [
    { name: 'amritsar', lat: 31.6, lon: 74.9, radius_nm: 250 },
    { name: 'jk', lat: 33.6, lon: 75.0, radius_nm: 150 },
    { name: 'delhi', lat: 28.6, lon: 77.2, radius_nm: 150 },
  ],
  all_india: [
    { name: 'north', lat: 33.0, lon: 76.0, radius_nm: 250 },
    { name: 'rajasthan', lat: 28.0, lon: 73.5, radius_nm: 250 },
    { name: 'up', lat: 27.0, lon: 81.0, radius_nm: 250 },
    { name: 'east', lat: 25.5, lon: 88.5, radius_nm: 250 },
    { name: 'northeast', lat: 26.0, lon: 94.0, radius_nm: 250 },
    { name: 'gujarat', lat: 23.0, lon: 70.5, radius_nm: 250 },
    { name: 'central', lat: 22.5, lon: 77.5, radius_nm: 250 },
    { name: 'odisha', lat: 21.0, lon: 84.5, radius_nm: 250 },
    { name: 'west', lat: 18.5, lon: 74.5, radius_nm: 250 },
    { name: 'deccan', lat: 16.5, lon: 80.5, radius_nm: 250 },
    { name: 'south', lat: 12.0, lon: 77.0, radius_nm: 250 },
    { name: 'andaman', lat: 11.6, lon: 92.7, radius_nm: 150 },
  ],
}

// Copy of scenarios/demo1.json (the standalone build has no file access).
export const SCENARIOS = [
  {
    id: 'demo1',
    file: 'demo1.json',
    description:
      'Scripted test for the evaluation slide: a jammer over the busy Delhi approach, then two spoofed aircraft, injected into real recorded traffic. Every effect is tagged INJECTED TEST ATTACK.',
    events: [
      { at_offset_s: 120, attack: { kind: 'jamming', center: [28.47, 77.2], radius_km: 60, strength: 0.7, position_loss: 0.3, duration_s: 900 } },
      { at_offset_s: 600, attack: { kind: 'spoof', hex: 'random', offset_km: 25, bearing_deg: 70, alt_offset_ft: 0, duration_s: 300 } },
      { at_offset_s: 900, attack: { kind: 'spoof', hex: 'random', offset_km: 0, bearing_deg: 0, alt_offset_ft: -2500, duration_s: 300 } },
    ],
  },
]

export class HttpError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.status = status
    this.detail = detail
  }
}

// ------------------------------------------------------------------ sample decoding
export function decodeSample(doc) {
  const [hexT, srcT, flightT, typeT] = ['hex', 'src', 'flight', 'type'].map((k) => doc.tables[k])
  const frames = doc.frames.map(([rel, rows]) => {
    const poll = doc.t0 + rel
    const recs = rows.map((a) => ({
      ts: poll - (a[3] || 0),
      poll_ts: poll,
      hex: hexT[a[0]],
      source: a[1] >= 0 ? srcT[a[1]] : 'unknown',
      flight: a[2] >= 0 ? flightT[a[2]] : null,
      lat: a[4],
      lon: a[5],
      last_lat: a[6],
      last_lon: a[7],
      alt_baro: a[8],
      alt_geom: a[9],
      on_ground: a[10] === 1,
      gs: a[11],
      track: a[12],
      nic: a[13],
      nac_p: a[14],
      src_type: a[15] >= 0 ? typeT[a[15]] : null,
      seen: a[16],
      seen_pos: a[17],
      gps_ok_before: a[18] != null ? poll + a[18] : null,
      gps_ok_lat: a[19],
      gps_ok_lon: a[20],
      injected: null,
      original: null,
    }))
    return { ts: poll, recs }
  })
  frames.sort((a, b) => a.ts - b.ts)
  return frames
}

// ------------------------------------------------------------------ state.py Window
class Window {
  constructor(keepS) {
    this.keepS = keepS
    this.recs = []
    this.lastPos = new Map()
  }
  get length() {
    return this.recs.length
  }
  add(records) {
    let n = 0
    for (const r of records) {
      if (r.lat != null) {
        const key = `${r.lat},${r.lon},${r.injected}`
        const slot = `${r.hex}|${r.source}`
        if (this.lastPos.get(slot) === key) continue
        this.lastPos.set(slot, key)
      }
      this.recs.push(r)
      n += 1
    }
    return n
  }
  prune(now) {
    const cutoff = now - this.keepS
    this.recs = this.recs.filter((r) => r.ts >= cutoff)
  }
  since(t0, t1) {
    return this.recs.filter((r) => r.ts >= t0 && (t1 == null || r.ts <= t1))
  }
  latestByHex(now, maxAge) {
    const cutoff = now - maxAge
    const best = new Map()
    for (const r of this.recs) {
      if (r.ts < cutoff || r.ts > now + 5) continue
      const cur = best.get(r.hex)
      if (!cur || r.ts > cur.ts || (r.ts === cur.ts && hasPosition(r) && !hasPosition(cur))) best.set(r.hex, r)
    }
    return best
  }
  restoreInjected(attackId) {
    let n = 0
    this.recs = this.recs.map((r) => {
      if (r.injected && r.injected.split(',').includes(attackId) && r.original) {
        n += 1
        return r.original
      }
      return r
    })
    if (n) this.lastPos.clear()
    return n
  }
  clear() {
    this.recs = []
    this.lastPos.clear()
  }
}

// ------------------------------------------------------------------ injector.py
// Deterministic "is this aircraft in the affected share?" (cyrb53 hash; the
// backend uses blake2b, so the exact aircraft chosen differ, the behaviour does not).
function hash01(str) {
  let h1 = 0xdeadbeef
  let h2 = 0x41c6ce57
  for (let i = 0; i < str.length; i++) {
    const ch = str.charCodeAt(i)
    h1 = Math.imul(h1 ^ ch, 2654435761)
    h2 = Math.imul(h2 ^ ch, 1597334677)
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909)
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909)
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)) / 2 ** 53
}
const selected = (attackId, hex, share, salt = '') => (share <= 0 ? false : share >= 1 ? true : hash01(`${attackId}|${salt}|${hex}`) < share)

const JAMMING_FIELDS = new Set(['center', 'radius_km', 'strength', 'position_loss', 'duration_s', 'active'])
const SPOOF_FIELDS = new Set(['hex', 'offset_km', 'bearing_deg', 'alt_offset_ft', 'duration_s', 'active'])
const GEOMETRY_FIELDS = new Set(['center', 'radius_km', 'hex'])

class Attack {
  constructor(props) {
    Object.assign(
      this,
      {
        active: true,
        duration_s: null,
        ended_ts: null,
        center: null,
        radius_km: 60,
        strength: 0.7,
        position_loss: 0.3,
        hex: null,
        offset_km: 25,
        bearing_deg: 45,
        alt_offset_ft: 0,
        max_aircraft_inside: 0,
      },
      props,
    )
    this.frozen = new Map()
  }
  live(now) {
    if (!this.active || this.ended_ts != null || now < this.activated_ts) return false
    return this.duration_s == null || now < this.activated_ts + this.duration_s
  }
  remaining(now) {
    if (this.duration_s == null || !this.live(now)) return null
    return Math.max(0, this.activated_ts + this.duration_s - now)
  }
  toDict(now) {
    const { frozen, ...rest } = this
    const d = { ...rest, center: this.center ? [...this.center] : null, label: LABEL }
    if (now != null) {
      d.live = this.live(now)
      d.remaining_s = this.remaining(now)
    }
    return d
  }
}

class Injector {
  constructor() {
    this.attacks = new Map()
    this.groundTruth = []
    this.seq = 1
  }
  addJamming(center, radius, strength, posLoss, duration, now) {
    const a = new Attack({ id: `jam-${this.seq++}`, kind: 'jamming', created_ts: now, activated_ts: now, duration_s: duration, center: [+center[0], +center[1]], radius_km: radius, strength, position_loss: posLoss })
    this.attacks.set(a.id, a)
    this.openEvent(a, now)
    return a
  }
  addSpoof(hex, offset, bearing, altOffset, duration, now) {
    const a = new Attack({ id: `spoof-${this.seq++}`, kind: 'spoof', created_ts: now, activated_ts: now, duration_s: duration, hex: hex.toLowerCase(), offset_km: offset, bearing_deg: bearing, alt_offset_ft: altOffset })
    this.attacks.set(a.id, a)
    this.openEvent(a, now)
    return a
  }
  update(id, changes, now) {
    const a = this.attacks.get(id)
    const allowed = a.kind === 'jamming' ? JAMMING_FIELDS : SPOOF_FIELDS
    const unknown = Object.keys(changes).filter((k) => !allowed.has(k))
    if (unknown.length) throw new HttpError(422, `cannot change ${JSON.stringify(unknown.sort())} on a ${a.kind} attack`)
    const wasLive = a.live(now)
    const same = (k, v) => (k === 'center' ? Array.isArray(v) && a.center && v[0] === a.center[0] && v[1] === a.center[1] : v === a[k])
    const geometryChanged = Object.entries(changes).some(([k, v]) => GEOMETRY_FIELDS.has(k) && !same(k, v))
    for (let [k, v] of Object.entries(changes)) {
      if (k === 'center' && v != null) v = [+v[0], +v[1]]
      if (k === 'hex' && v != null) v = String(v).toLowerCase()
      a[k] = v
    }
    if (changes.active === true && !wasLive) {
      a.activated_ts = now
      a.ended_ts = null
    }
    if (geometryChanged) a.frozen.clear()
    const isLive = a.live(now)
    if (wasLive && (!isLive || geometryChanged)) this.closeEvent(a.id, now)
    if (isLive && (!wasLive || geometryChanged)) this.openEvent(a, now)
    else if (isLive) this.refreshEvent(a)
    return a
  }
  remove(id, now) {
    const a = this.attacks.get(id)
    if (!a) return null
    this.attacks.delete(id)
    a.ended_ts = now
    this.closeEvent(id, now)
    return a
  }
  reset(now) {
    const ids = [...this.attacks.keys()]
    ids.forEach((id) => this.remove(id, now))
    return ids
  }
  rebase(oldNow, newNow) {
    const delta = newNow - oldNow
    for (const a of this.attacks.values()) {
      const wasLive = a.live(oldNow)
      a.created_ts += delta
      a.activated_ts += delta
      if (a.ended_ts != null) a.ended_ts += delta
      a.frozen.clear()
      if (wasLive) {
        this.closeEvent(a.id, oldNow)
        this.openEvent(a, newNow)
      }
    }
  }
  clearAll() {
    this.attacks.clear()
    this.groundTruth = []
  }
  liveAttacks(now) {
    for (const a of this.attacks.values()) {
      if (a.ended_ts == null && a.active && a.duration_s != null && now >= a.activated_ts + a.duration_s) {
        this.closeEvent(a.id, now)
        a.ended_ts = now
      }
    }
    return [...this.attacks.values()].filter((a) => a.live(now))
  }
  apply(records, now) {
    const live = this.liveAttacks(now)
    if (!live.length) return records
    return records.map((pristine) => {
      let cur = pristine
      for (const a of live) {
        const changed = a.kind === 'jamming' ? this.jam(cur, pristine, a, now) : this.spoof(cur, pristine, a)
        if (changed) cur = changed
      }
      return cur
    })
  }
  jam(cur, pristine, a, now) {
    if (pristine.on_ground || !a.center) return null
    const pos = bestPosition(pristine)
    if (!pos) return null
    if (haversineKm(pos[0], pos[1], a.center[0], a.center[1]) > a.radius_km) {
      a.frozen.delete(pristine.hex)
      return null
    }
    if (!selected(a.id, pristine.hex, a.strength)) return null
    const changes = { nac_p: 0, nic: 0 }
    if (hasPosition(pristine) && selected(a.id, pristine.hex, a.position_loss, 'pos')) {
      if (!a.frozen.has(pristine.hex)) a.frozen.set(pristine.hex, [pristine.lat, pristine.lon, now])
      const [lat0, lon0, t0] = a.frozen.get(pristine.hex)
      Object.assign(changes, { lat: null, lon: null, last_lat: lat0, last_lon: lon0, seen_pos: Math.max(pristine.seen_pos || 0, now - t0) })
    }
    return tag(cur, pristine, a.id, changes)
  }
  spoof(cur, pristine, a) {
    if (pristine.hex !== a.hex || !hasPosition(pristine) || !hasPosition(cur)) return null
    const [lat, lon] = destinationPoint(pristine.lat, pristine.lon, a.bearing_deg, a.offset_km)
    const changes = { lat, lon }
    if (a.alt_offset_ft) {
      const base = pristine.alt_geom ?? pristine.alt_baro
      if (base != null) changes.alt_geom = Math.round(base + a.alt_offset_ft)
    }
    return tag(cur, pristine, a.id, changes)
  }
  aircraftInside(a, latest) {
    if (a.kind !== 'jamming' || !a.center) return 0
    return countInside(a.center, a.radius_km, latest)
  }
  openEvent(a, now) {
    this.groundTruth.push({
      attack_id: a.id,
      kind: a.kind,
      start_ts: now,
      end_ts: null,
      center: a.center,
      radius_km: a.radius_km,
      strength: a.strength,
      position_loss: a.position_loss,
      hex: a.hex,
      offset_km: a.offset_km,
      bearing_deg: a.bearing_deg,
      alt_offset_ft: a.alt_offset_ft,
    })
  }
  refreshEvent(a) {
    for (let i = this.groundTruth.length - 1; i >= 0; i--) {
      const g = this.groundTruth[i]
      if (g.attack_id === a.id && g.end_ts == null) {
        Object.assign(g, { strength: a.strength, position_loss: a.position_loss, offset_km: a.offset_km, bearing_deg: a.bearing_deg, alt_offset_ft: a.alt_offset_ft })
        return
      }
    }
  }
  closeEvent(id, now) {
    for (let i = this.groundTruth.length - 1; i >= 0; i--) {
      const g = this.groundTruth[i]
      if (g.attack_id === id && g.end_ts == null) {
        g.end_ts = now
        return
      }
    }
  }
}

function countInside(center, radiusKm, records) {
  const hexes = new Set()
  for (const r of records) {
    if (r.on_ground) continue
    const pos = bestPosition(r.original || r)
    if (pos && haversineKm(pos[0], pos[1], center[0], center[1]) <= radiusKm) hexes.add(r.hex)
  }
  return hexes.size
}

function tag(cur, pristine, attackId, changes) {
  const ids = cur.injected ? cur.injected.split(',') : []
  if (!ids.includes(attackId)) ids.push(attackId)
  return { ...cur, ...changes, injected: ids.join(','), original: pristine }
}

// ------------------------------------------------------------------ sentinel.py (+ a simulated box)
const BASELINE_S = 120
const SNR_DROP_DB = 10
const FIX_LOSS_S = 5
const MOVE_M = 50
const ALT_JUMP_M = 100
const STATUSES = ['OK', 'SEARCHING', 'JAMMING', 'SPOOF', 'OFFLINE']

class SentinelStore {
  constructor(offlineS = 10, maxLen = 2000) {
    this.offlineS = offlineS
    this.maxLen = maxLen
    this.packets = new Map()
    this.state = new Map()
  }
  check(st, p, now) {
    const fix = Boolean(p.fix)
    const { avg_snr: snr, lat, lon, alt } = p
    if (!fix) {
      st.fix_since = null
      if (st.baseline_snr != null && st.last_fix_ts != null && now - st.last_fix_ts > FIX_LOSS_S) return ['JAMMING', `fix lost for ${Math.round(now - st.last_fix_ts)} s`]
      return st.baseline_snr == null ? ['SEARCHING', 'no fix yet'] : ['OK', null]
    }
    st.last_fix_ts = now
    if (st.fix_since == null) st.fix_since = now
    if (st.baseline_snr == null) {
      if (snr != null) st.calib.push([snr, lat, lon, alt])
      if (now - st.fix_since >= BASELINE_S && st.calib.length) {
        const med = (xs) => {
          const s = [...xs].sort((a, b) => a - b)
          const m = Math.floor(s.length / 2)
          return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2
        }
        st.baseline_snr = med(st.calib.map((c) => c[0]))
        st.ref = [med(st.calib.map((c) => c[1])), med(st.calib.map((c) => c[2])), med(st.calib.map((c) => c[3]))]
        st.calib = []
      }
      return ['OK', st.baseline_snr == null ? 'learning baseline' : null]
    }
    if (snr != null && snr <= st.baseline_snr - SNR_DROP_DB) return ['JAMMING', `signal ${Math.round(st.baseline_snr - snr)} dB below baseline`]
    if (st.ref && lat != null && lon != null) {
      const moved = haversineKm(lat, lon, st.ref[0], st.ref[1]) * 1000
      if (moved > MOVE_M) return ['SPOOF', `fixed box appears to move ${Math.round(moved)} m`]
      if (alt != null && st.ref[2] != null && Math.abs(alt - st.ref[2]) > ALT_JUMP_M) return ['SPOOF', `altitude jumped ${Math.round(Math.abs(alt - st.ref[2]))} m`]
    }
    return ['OK', null]
  }
  add(packet, recvTs) {
    const device = String(packet.id || 'sentinel-1')
    if (!this.state.has(device)) this.state.set(device, { fix_since: null, last_fix_ts: null, calib: [], baseline_snr: null, ref: null })
    const st = this.state.get(device)
    const [serverStatus, why] = this.check(st, packet, recvTs)
    const status = STATUSES.includes(String(packet.status || 'OK').toUpperCase()) ? String(packet.status || 'OK').toUpperCase() : String(packet.status)
    const entry = { ...packet, id: device, recv_ts: recvTs, status, server_status: serverStatus, server_reason: why, baseline_snr: st.baseline_snr }
    if (!this.packets.has(device)) this.packets.set(device, [])
    const q = this.packets.get(device)
    q.push(entry)
    if (q.length > this.maxLen) q.shift()
    return entry
  }
  latest(now) {
    const out = []
    for (const q of this.packets.values()) {
      const last = { ...q[q.length - 1] }
      const age = now - last.recv_ts
      last.age_s = Math.round(age * 10) / 10
      if (age > this.offlineS) last.status = last.server_status = 'OFFLINE'
      out.push(last)
    }
    return out
  }
  alerts(now) {
    return this.latest(now)
      .filter((e) => e.server_status === 'JAMMING' || e.server_status === 'SPOOF')
      .map((e) => ({
        id: `sentinel-${e.id}`,
        kind: `sentinel_${e.server_status.toLowerCase()}`,
        device: e.id,
        lat: e.lat,
        lon: e.lon,
        severity: 'high',
        label: 'SIGNAL TEST (antenna covered)',
        injected: false,
        message: `${e.id}: ${e.server_status} - ${e.server_reason}`,
      }))
  }
  history(device, minutes, now) {
    const cutoff = now - minutes * 60
    return (this.packets.get(device) || []).filter((p) => p.recv_ts >= cutoff)
  }
}

/** A pretend ESP32 + NEO-6M on a table in Chennai, posting every 2 s. */
class FakeBox {
  constructor(store) {
    this.store = store
    this.coverUntil = 0
    this.seed = 7
    const now = Date.now() / 1000
    for (let t = now - 300; t < now; t += 2) this.post(t) // as if it had been running for 5 minutes
  }
  rand() {
    this.seed = (this.seed * 16807) % 2147483647
    return this.seed / 2147483647
  }
  post(t) {
    const covered = t < this.coverUntil
    const base = [44, 43, 41, 40, 40, 39, 38, 38, 36]
    const snr = base.map((v) => Math.round(v + (this.rand() - 0.5) * 3 - (covered ? 14 : 0)))
    const avg = Math.round((snr.reduce((s, v) => s + v, 0) / snr.length) * 10) / 10
    this.store.add(
      {
        id: 'sentinel-1',
        ts: Math.round(t * 1000) % 1e9,
        lat: 13.0108 + (this.rand() - 0.5) * 2e-5,
        lon: 80.2296 + (this.rand() - 0.5) * 2e-5,
        alt: 12 + (this.rand() - 0.5) * 2,
        fix: true,
        sats_used: covered ? 3 + Math.round(this.rand()) : 8,
        sats_in_view: 11,
        avg_snr: avg,
        hdop: covered ? 3.4 : 0.9,
        status: covered ? 'JAMMING' : 'OK',
        snr_list: snr,
      },
      t,
    )
  }
  cover(seconds) {
    this.coverUntil = Date.now() / 1000 + seconds
  }
}

// ------------------------------------------------------------------ runtime.py
export class Engine {
  constructor(frames, files) {
    this.frames = frames
    this.times = frames.map((f) => f.ts)
    this.files = files
    this.nRecords = frames.reduce((s, f) => s + f.recs.length, 0)
    this.cfg = { ...DEFAULT_DETECTION }
    this.window = new Window(WINDOW_KEEP_S)
    this.injector = new Injector()
    this.incidents = new IncidentTracker()
    this.sentinel = new SentinelStore()
    this.box = new FakeBox(this.sentinel)
    this.mode = 'replay'
    this.region = 'north_india'
    this.clockTs = this.times[0]
    this.speed = 1
    this.paused = false
    this.finished = false
    this.idx = 0
    this.detections = []
    this.flagLog = []
    this.prevStates = new Map()
    this.prevFlagged = new Set()
    this.scenario = null
    this.lastTick = null
    this.listeners = new Set()
    this.lastWall = performance.now()
    this.seek(this.defaultStart())
    this.timers = [window.setInterval(() => this.advance(), 200), window.setInterval(() => this.tick(), TICK_S * 1000), window.setInterval(() => this.box.post(Date.now() / 1000), 2000)]
    this.tick()
  }

  now() {
    return this.mode === 'live' ? Date.now() / 1000 : this.clockTs
  }

  // ---- replay
  get tStart() {
    return this.times[0] || 0
  }
  get tEnd() {
    return this.times[this.times.length - 1] || 0
  }
  segments() {
    const segs = []
    let start = null
    this.times.forEach((t, i) => {
      if (start == null) start = t
      else if (t - this.times[i - 1] > GAP_S) {
        segs.push([start, this.times[i - 1]])
        start = t
      }
    })
    if (start != null) segs.push([start, this.times[this.times.length - 1]])
    return segs
  }
  defaultStart() {
    const [s0, s1] = this.segments().reduce((best, s) => (s[1] - s[0] > best[1] - best[0] ? s : best), [this.tStart, this.tStart])
    return s0 + Math.min(1200, WINDOW_KEEP_S, (s1 - s0) * 0.4)
  }
  clearForTimeJump() {
    this.window.clear()
    this.incidents.reset()
    this.prevStates.clear()
    this.prevFlagged.clear()
    this.scenario = null
  }
  seek(ts) {
    ts = Math.max(this.tStart, Math.min(Number(ts), this.tEnd))
    const old = this.now()
    this.clearForTimeJump()
    this.injector.rebase(old, ts)
    this.clockTs = ts
    let lo = 0
    while (lo < this.times.length && this.times[lo] < ts - WINDOW_KEEP_S) lo++
    let hi = lo
    while (hi < this.times.length && this.times[hi] <= ts) hi++
    for (let i = lo; i < hi; i++) this.window.add(this.frames[i].recs)
    this.idx = hi
    this.finished = false
    return ts
  }
  advance() {
    const t = performance.now()
    const dt = (t - this.lastWall) / 1000
    this.lastWall = t
    if (this.mode !== 'replay' || this.paused || this.finished) return
    let target = this.clockTs + dt * this.speed
    if (this.idx < this.frames.length && this.frames[this.idx].ts - target > GAP_S) target = this.frames[this.idx].ts
    while (this.idx < this.frames.length && this.frames[this.idx].ts <= target) {
      const f = this.frames[this.idx]
      this.window.add(this.injector.apply(f.recs, f.ts))
      this.idx += 1
    }
    this.clockTs = Math.min(target, this.tEnd)
    if (this.idx >= this.frames.length) this.seek(this.defaultStart())
  }
  replayStatus() {
    if (this.mode !== 'replay') return null
    const span = Math.max(1e-9, this.tEnd - this.tStart)
    return {
      files: this.files,
      sample: true,
      loaded: true,
      error: null,
      t_start: this.tStart,
      t_end: this.tEnd,
      ts: this.clockTs,
      progress: Math.round(((this.clockTs - this.tStart) / span) * 10000) / 10000,
      speed: this.speed,
      paused: this.paused,
      finished: this.finished,
      frames: this.frames.length,
      segments: this.segments().length,
      records: this.nRecords,
    }
  }
  setMode(mode, speed) {
    // reset_experiment()
    this.window.clear()
    this.injector.clearAll()
    this.incidents.reset()
    this.detections = []
    this.flagLog = []
    this.prevStates.clear()
    this.prevFlagged.clear()
    this.scenario = null
    this.mode = mode
    if (mode === 'replay') {
      this.speed = speed || 1
      this.paused = false
      this.clockTs = this.tStart
      this.seek(this.defaultStart())
    }
    this.tick()
  }

  // ---- attacks
  latestAircraft() {
    return this.window.latestByHex(this.now(), AIRCRAFT_MAX_AGE_S)
  }
  previewCircle(lat, lon, radiusKm) {
    const now = this.now()
    const cfg = this.cfg
    const recs = this.window.since(now - cfg.jam_window_s, now)
    const perCell = new Map()
    for (const r of recs) {
      const pos = bestPosition(r.original || r)
      if (r.on_ground || !pos || haversineKm(pos[0], pos[1], lat, lon) > radiusKm) continue
      const cell = latLngToCell(pos[0], pos[1], cfg.h3_res)
      if (!perCell.has(cell)) perCell.set(cell, new Set())
      perCell.get(cell).add(r.hex)
    }
    const best = Math.max(0, ...[...perCell.values()].map((s) => s.size))
    const ok = best >= cfg.min_aircraft
    return {
      aircraft_now: countInside([lat, lon], radiusKm, this.latestAircraft().values()),
      aircraft_in_window: countInside([lat, lon], radiusKm, recs),
      cells_under_circle: perCell.size,
      busiest_cell_aircraft: best,
      min_aircraft_per_cell: cfg.min_aircraft,
      likely_detectable: ok,
      hint: ok
        ? null
        : 'Too few aircraft per cell here for the crowd method. Try a busier area, a bigger radius, a longer window, or bigger cells (Cell size: res 2).',
    }
  }
  createAttack(body) {
    const now = this.now()
    let a
    let extra = {}
    if (body.kind === 'jamming') {
      a = this.injector.addJamming(body.center, body.radius_km ?? 60, body.strength ?? 0.7, body.position_loss ?? 0.3, body.duration_s ?? null, now)
      extra = this.previewCircle(a.center[0], a.center[1], a.radius_km)
    } else if (body.kind === 'spoof') {
      let hex = body.hex || 'random'
      if (hex === 'random') {
        const cand = [...this.latestAircraft().values()].filter((r) => !r.on_ground && hasPosition(r) && !r.injected).map((r) => r.hex)
        hex = cand.length ? cand[Math.floor(Math.random() * cand.length)] : null
      } else hex = String(hex).toLowerCase()
      if (!hex) throw new HttpError(409, 'no airborne aircraft available to spoof right now')
      a = this.injector.addSpoof(hex, body.offset_km ?? 25, body.bearing_deg ?? 45, body.alt_offset_ft ?? 0, body.duration_s === undefined ? 300 : body.duration_s, now)
    } else throw new HttpError(422, `unknown attack kind ${body.kind}`)
    return { attack_id: a.id, attack: a.toDict(now), ...extra }
  }
  startScenario(id) {
    const sc = SCENARIOS.find((s) => s.id === id)
    if (!sc) throw new HttpError(404, `no scenario '${id}'`)
    const now = this.now()
    this.scenario = { id, start_ts: now, pending: sc.events.map((e) => [now + e.at_offset_s, e.attack]).sort((a, b) => a[0] - b[0]), fired: [] }
    return this.scenarioStatus()
  }
  scenarioStatus() {
    const s = this.scenario
    if (!s) return null
    return { id: s.id, start_ts: s.start_ts, fired: s.fired, remaining: s.pending.length, next_ts: s.pending.length ? s.pending[0][0] : null }
  }
  fireScenario(now) {
    const s = this.scenario
    if (!s) return
    while (s.pending.length && s.pending[0][0] <= now) {
      const [, body] = s.pending.shift()
      try {
        s.fired.push(this.createAttack(body).attack_id)
      } catch (e) {
        s.fired.push(`skipped: ${e.message}`)
      }
    }
  }

  // ---- tick
  computeTick() {
    const now = this.now()
    const cfg = this.cfg
    this.fireScenario(now)
    this.window.prune(now)
    const recs = this.window.since(now - cfg.jam_window_s, now)
    const cells = classifyCells(recs, cfg)
    const flags = flagAircraft(recs, cfg)
    const spoofFlagged = new Set([...flags].filter(([, why]) => why.some((c) => SPOOF_REASONS.has(c))).map(([h]) => h))
    for (const h of spoofFlagged) if (!this.prevFlagged.has(h)) this.flagLog.push({ ts: now, hex: h, reasons: flags.get(h) })
    this.prevFlagged = spoofFlagged
    for (const [cell, n] of spoofedCells(flags, recs, cfg)) {
      if (n >= 1) {
        const c = cells.get(cell) || { h3: cell, n_aircraft: n, n_bad: 0, frac_bad: 0, lower_bound: 0, state: 'spoofing', n_injected: 0, bad_hexes: [], reasons: {} }
        c.state = 'spoofing'
        cells.set(cell, c)
      }
    }
    for (const [cell, c] of cells) {
      if ((c.state === 'jammed' || c.state === 'spoofing') && this.prevStates.get(cell) !== c.state)
        this.detections.push({ ts: now, h3: cell, state: c.state, n_bad: c.n_bad, n_aircraft: c.n_aircraft, n_injected: c.n_injected })
    }
    this.prevStates = new Map([...cells].map(([k, c]) => [k, c.state]))

    const latest = this.latestAircraft()
    const alarm = new Map([...cells].filter(([, c]) => c.state === 'jammed' || c.state === 'spoofing').map(([k, c]) => [k, c.state]))
    const injectedCells = new Set([...cells].filter(([, c]) => (c.state === 'jammed' || c.state === 'spoofing') && c.n_bad && c.n_injected === c.n_bad).map(([k]) => k))
    const wall = Date.now() / 1000
    const alerts = [...earlyWarnings(latest, alarm, cfg, now, injectedCells), ...this.sentinel.alerts(wall)]
    this.incidents.update(cells, recs, cfg, now, flags)
    for (const a of this.injector.liveAttacks(now)) a.max_aircraft_inside = Math.max(a.max_aircraft_inside, this.injector.aircraftInside(a, latest.values()))

    const aircraft = []
    for (const r of latest.values()) {
      const pos = bestPosition(r)
      if (!pos) continue
      aircraft.push({
        hex: r.hex,
        flight: r.flight,
        lat: Math.round(pos[0] * 1e5) / 1e5,
        lon: Math.round(pos[1] * 1e5) / 1e5,
        pos_lost: !hasPosition(r),
        alt_baro: r.alt_baro,
        alt_geom: r.alt_geom,
        on_ground: r.on_ground,
        gs: r.gs,
        track: r.track,
        nic: r.nic,
        nac_p: r.nac_p,
        source: r.source,
        age_s: Math.round((now - r.ts) * 10) / 10,
        bad: badReason(r, cfg),
        spoof: flags.get(r.hex) || [],
        injected: r.injected,
      })
    }
    const stateCounts = {}
    for (const c of cells.values()) stateCounts[c.state] = (stateCounts[c.state] || 0) + 1

    this.lastTick = {
      type: 'tick',
      ts: now,
      mode: this.mode,
      region: this.region,
      h3_res: cfg.h3_res,
      window_s: cfg.jam_window_s,
      cells: toGeoJSON(cells),
      aircraft,
      alerts,
      incidents_summary: this.incidents.summary(),
      attacks: [...this.injector.attacks.values()].map((a) => a.toDict(now)),
      sentinel: this.sentinel.latest(wall),
      replay: this.replayStatus(),
      scenario: this.scenarioStatus(),
      stats: { aircraft: aircraft.length, cells: stateCounts, window_records: this.window.length },
      credits: ATTRIBUTION,
      standalone: true,
    }
    return this.lastTick
  }
  tick() {
    let payload
    try {
      payload = this.computeTick()
    } catch (e) {
      console.error('[standalone] tick failed', e) // keep ticking, like the backend
      return
    }
    const text = JSON.stringify(payload)
    for (const fn of this.listeners) fn(text)
  }
  subscribe(fn) {
    this.listeners.add(fn)
    if (this.lastTick) window.setTimeout(() => fn(JSON.stringify(this.lastTick)), 0)
    return () => this.listeners.delete(fn)
  }

  health() {
    return {
      mode: this.mode,
      region: this.region,
      points: REGIONS[this.region] || [],
      sources: ['adsb.fi', 'adsb.lol'],
      clock_ts: this.now(),
      last_poll_ts: null,
      n_aircraft: this.latestAircraft().size,
      window_records: this.window.length,
      source_stats: {},
      replay: this.replayStatus(),
      attacks_live: this.injector.liveAttacks(this.now()).length,
      tick_s: TICK_S,
      run_id: 'standalone',
      regions: Object.keys(REGIONS).sort(),
      recordings_dir: '(bundled sample, in the browser)',
      standalone: true,
    }
  }
  evaluation() {
    const coverage = {}
    for (const a of this.injector.attacks.values()) coverage[a.id] = a.max_aircraft_inside
    return evaluate(this.injector.groundTruth, this.detections, this.cfg, this.now(), coverage, this.flagLog)
  }
}
