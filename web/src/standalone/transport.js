// fetch() and WebSocket stand-ins that route the dashboard's calls to the
// in-browser Engine instead of the FastAPI backend (standalone build only).
// Paths, bodies, status codes and error shapes follow backend/app/api/routes.py.
import { REGIONS, SCENARIOS, HttpError } from './engine.js'
import { validateDetection, DEFAULT_DETECTION } from './detect.js'

const IST_OFFSET_S = 5.5 * 3600

const fieldError = (loc, msg, type = 'value_error') => ({ loc: ['body', ...loc], msg, type })

function checkRange(errors, body, key, lo, hi, { optional = true, integer = false, lt = false } = {}) {
  if (!(key in body)) return
  const v = body[key]
  if (v === null && optional) return
  if (typeof v !== 'number' || !Number.isFinite(v)) {
    errors.push(fieldError([key], 'Input should be a valid number', 'float_type'))
    return
  }
  if (integer && !Number.isInteger(v)) errors.push(fieldError([key], 'Input should be a valid integer', 'int_type'))
  if (v < lo) errors.push(fieldError([key], `Input should be greater than or equal to ${lo}`, 'greater_than_equal'))
  if (lt ? v >= hi : v > hi) errors.push(fieldError([key], `Input should be less than ${lt ? '' : 'or equal to '}${hi}`, lt ? 'less_than' : 'less_than_equal'))
}

function validateAttack(body) {
  const errors = []
  if (!body || (body.kind !== 'jamming' && body.kind !== 'spoof')) {
    errors.push(fieldError(['kind'], "Input tag should be 'jamming' or 'spoof'", 'union_tag_invalid'))
    return errors
  }
  if (body.kind === 'jamming') {
    if (!Array.isArray(body.center) || body.center.length !== 2 || body.center.some((x) => typeof x !== 'number')) errors.push(fieldError(['jamming', 'center'], 'Field required: [lat, lon]', 'missing'))
    checkRange(errors, body, 'radius_km', 10, 150)
    checkRange(errors, body, 'strength', 0, 1)
    checkRange(errors, body, 'position_loss', 0, 1)
    checkRange(errors, body, 'duration_s', 60, 1800)
  } else {
    checkRange(errors, body, 'offset_km', 0, 80)
    checkRange(errors, body, 'bearing_deg', 0, 360, { lt: true })
    checkRange(errors, body, 'alt_offset_ft', -4000, 4000)
    checkRange(errors, body, 'duration_s', 30, 1800)
  }
  return errors
}

const PATCH_FIELDS = new Set(['active', 'duration_s', 'center', 'radius_km', 'strength', 'position_loss', 'hex', 'offset_km', 'bearing_deg', 'alt_offset_ft'])
function validatePatch(body) {
  const errors = []
  for (const k of Object.keys(body || {})) if (!PATCH_FIELDS.has(k)) errors.push(fieldError([k], 'Extra inputs are not permitted', 'extra_forbidden'))
  checkRange(errors, body, 'duration_s', 30, 1800)
  checkRange(errors, body, 'radius_km', 10, 150)
  checkRange(errors, body, 'strength', 0, 1)
  checkRange(errors, body, 'position_loss', 0, 1)
  checkRange(errors, body, 'offset_km', 0, 80)
  checkRange(errors, body, 'bearing_deg', 0, 360, { lt: true })
  checkRange(errors, body, 'alt_offset_ft', -4000, 4000)
  return errors
}

function recordingsList(files, t0) {
  return files.map((name) => {
    const parts = name.split('_')
    const stamp = parts.length >= 4 ? `${parts[1]}_${parts[2]}` : name
    return { name, bytes: null, utc_hour: stamp, starts: new Date((t0 + IST_OFFSET_S) * 1000).toISOString().slice(0, 16).replace('T', ' ') + ' IST' }
  })
}

/** Returns [status, body]. */
function route(engine, method, path, query, body) {
  const seg = path.replace(/^\/api\/?/, '').split('/').filter(Boolean)
  const now = () => engine.now()
  const is = (m, ...parts) => method === m && seg.length === parts.length && parts.every((p, i) => p === '*' || p === seg[i])

  if (is('GET', 'health')) return [200, engine.health()]
  if (is('GET', 'aircraft')) return [200, (engine.lastTick || engine.computeTick()).aircraft]
  if (is('GET', 'cells')) return [200, (engine.lastTick || engine.computeTick()).cells]
  if (is('GET', 'alerts')) return [200, engine.lastTick?.alerts || []]

  if (is('POST', 'mode')) {
    if (body?.mode !== 'live' && body?.mode !== 'replay') return [422, [fieldError(['mode'], "Input should be 'live' or 'replay'", 'literal_error')]]
    engine.setMode(body.mode, body.speed)
    return [200, engine.health()]
  }
  if (is('GET', 'regions')) return [200, { current: engine.region, points: REGIONS[engine.region] || [], presets: REGIONS }]
  if (is('POST', 'region')) {
    if (!body?.name || !REGIONS[body.name]) return [422, `unknown region '${body?.name}'; choose one of ${JSON.stringify(Object.keys(REGIONS).sort())}`]
    engine.region = body.name
    return [200, { current: engine.region, points: REGIONS[engine.region], note: 'applies to live polling from the next sweep; replay plays whatever was recorded' }]
  }
  if (is('GET', 'recordings')) return [200, recordingsList(engine.files, engine.tStart)]

  if (seg[0] === 'replay') {
    if (engine.mode !== 'replay') return [409, 'not in replay mode']
    if (is('GET', 'replay')) return [200, engine.replayStatus()]
    if (is('POST', 'replay', 'seek')) {
      if (typeof body?.ts !== 'number') return [422, [fieldError(['ts'], 'Field required', 'missing')]]
      engine.seek(body.ts)
      engine.tick()
      return [200, engine.replayStatus()]
    }
    if (is('POST', 'replay', 'speed')) {
      const sp = body?.speed
      if (typeof sp !== 'number' || sp < 0.1 || sp > 20) return [422, [fieldError(['speed'], 'Input should be between 0.1 and 20', 'less_than_equal')]]
      engine.speed = sp
      return [200, engine.replayStatus()]
    }
    if (is('POST', 'replay', 'pause')) {
      engine.paused = true
      return [200, engine.replayStatus()]
    }
    if (is('POST', 'replay', 'play')) {
      engine.paused = false
      return [200, engine.replayStatus()]
    }
  }

  if (is('GET', 'config', 'detection')) return [200, { ...engine.cfg }]
  if (is('PATCH', 'config', 'detection')) {
    const [next, errors] = validateDetection(engine.cfg, body)
    if (errors) return [422, errors]
    engine.cfg = next
    return [200, { ...engine.cfg }]
  }
  if (is('DELETE', 'config', 'detection')) {
    engine.cfg = { ...DEFAULT_DETECTION }
    return [200, { ...engine.cfg }]
  }

  if (is('GET', 'attacks')) return [200, [...engine.injector.attacks.values()].map((a) => a.toDict(now()))]
  if (is('GET', 'attacks', 'preview')) {
    const lat = Number(query.get('lat'))
    const lon = Number(query.get('lon'))
    const r = Number(query.get('radius_km'))
    if (![lat, lon, r].every(Number.isFinite)) return [422, [{ loc: ['query', 'lat'], msg: 'Field required', type: 'missing' }]]
    return [200, engine.previewCircle(lat, lon, r)]
  }
  if (is('POST', 'attacks')) {
    const errors = validateAttack(body)
    if (errors.length) return [422, errors]
    return [200, engine.createAttack(body)]
  }
  if (is('PATCH', 'attacks', '*')) {
    const id = decodeURIComponent(seg[1])
    if (!engine.injector.attacks.has(id)) return [404, `no attack ${id}`]
    const errors = validatePatch(body)
    if (errors.length) return [422, errors]
    const a = engine.injector.update(id, body, now())
    return [200, a.toDict(now())]
  }
  if (is('DELETE', 'attacks', '*')) {
    const id = decodeURIComponent(seg[1])
    const a = engine.injector.remove(id, now())
    if (!a) return [404, `no attack ${id}`]
    const restored = engine.window.restoreInjected(id)
    return [200, { deleted: id, records_restored: restored }]
  }
  if (is('DELETE', 'attacks')) {
    const ids = engine.injector.reset(now())
    const restored = ids.reduce((s, id) => s + engine.window.restoreInjected(id), 0)
    return [200, { deleted: ids, records_restored: restored }]
  }

  if (is('GET', 'incidents')) return [200, engine.incidents.summary()]
  if (is('GET', 'incidents', '*')) {
    const inc = engine.realIncidents.get(decodeURIComponent(seg[1])) || engine.incidents.get(decodeURIComponent(seg[1]))
    return inc ? [200, inc] : [404, `no incident ${seg[1]}`]
  }
  if (is('GET', 'incidents', '*', 'report.pdf')) return [501, 'PDF reports are generated by the Python backend; this standalone build has none.']

  if (is('GET', 'evaluation')) return [200, engine.evaluation()]
  if (is('GET', 'scenarios')) return [200, { available: SCENARIOS.map(({ id, file, description, events }) => ({ id, file, description, events: events.length })), running: engine.scenarioStatus() }]
  if (is('POST', 'scenarios', '*', 'run')) return [200, engine.startScenario(decodeURIComponent(seg[1]))]

  if (is('GET', 'sentinel', 'latest')) return [200, engine.sentinel.latest(Date.now() / 1000)]
  if (is('GET', 'sentinel', 'history')) {
    const id = query.get('id') || 'sentinel-1'
    const minutes = Number(query.get('minutes') || 10)
    return [200, engine.sentinel.history(id, minutes, Date.now() / 1000)]
  }
  if (is('POST', 'sentinel')) {
    const entry = engine.sentinel.add(body || {}, Date.now() / 1000)
    return [200, { ok: true, status: entry.status, recv_ts: entry.recv_ts }]
  }

  // GET /api/cells/{h3}/summary is not built on the real backend yet either.
  return [404, 'Not Found']
}

export function makeTransport(engine) {
  const fetchImpl = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, window.location.href)
    const method = (init.method || 'GET').toUpperCase()
    let body
    if (init.body) {
      try {
        body = JSON.parse(init.body)
      } catch {
        return new Response(JSON.stringify({ detail: 'JSON decode error' }), { status: 422, headers: { 'content-type': 'application/json' } })
      }
    }
    // A tiny delay keeps loading states honest without slowing anything down.
    await new Promise((r) => setTimeout(r, 40))
    let status
    let data
    try {
      ;[status, data] = route(engine, method, url.pathname, url.searchParams, body)
    } catch (e) {
      if (e instanceof HttpError) [status, data] = [e.status, e.detail]
      else {
        console.error('[standalone] route failed', e)
        ;[status, data] = [500, String(e?.message || e)]
      }
    }
    const payload = status >= 400 ? { detail: data } : data
    return new Response(JSON.stringify(payload), { status, headers: { 'content-type': 'application/json' } })
  }

  class StandaloneSocket {
    constructor() {
      this.readyState = 0
      this.onopen = null
      this.onmessage = null
      this.onclose = null
      this.onerror = null
      window.setTimeout(() => {
        if (this.readyState !== 0) return
        this.readyState = 1
        this.onopen?.({})
        this.unsub = engine.subscribe((text) => this.readyState === 1 && this.onmessage?.({ data: text }))
      }, 30)
    }
    send() {}
    close() {
      if (this.readyState === 3) return
      this.readyState = 3
      this.unsub?.()
      this.onclose?.({})
    }
  }

  return { fetch: fetchImpl, WebSocket: StandaloneSocket }
}
