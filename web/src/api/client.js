// Thin wrappers around the backend REST API (docs/FRONTEND_HANDOVER.md §5).
// Every call goes through `transport`, so the standalone build can swap in
// its in-browser backend without touching any component.
import { API_BASE } from '../config.js'

const transport = {
  fetch: (...args) => window.fetch(...args),
  WebSocket: typeof window !== 'undefined' ? window.WebSocket : undefined,
}

export function setTransport(t) {
  Object.assign(transport, t)
}
export const getTransport = () => transport

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : `HTTP ${status}`)
    this.status = status
    this.detail = detail
  }
}

async function request(method, path, body) {
  let res
  try {
    res = await transport.fetch(`${API_BASE}/api${path}`, {
      method,
      headers: body !== undefined ? { 'content-type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (e) {
    throw new ApiError(0, 'Cannot reach the backend. Is uvicorn running on port 8000?')
  }
  const text = await res.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    data = text
  }
  if (!res.ok) throw new ApiError(res.status, data && typeof data === 'object' && 'detail' in data ? data.detail : data)
  return data
}

const q = (params) =>
  Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&')

const id = (s) => encodeURIComponent(s)

export const api = {
  health: () => request('GET', '/health'),
  setMode: (mode, extra = {}) => request('POST', '/mode', { mode, ...extra }),
  regions: () => request('GET', '/regions'),
  setRegion: (name) => request('POST', '/region', { name }),
  recordings: () => request('GET', '/recordings'),

  replay: () => request('GET', '/replay'),
  seek: (ts) => request('POST', '/replay/seek', { ts }),
  speed: (speed) => request('POST', '/replay/speed', { speed }),
  pause: () => request('POST', '/replay/pause'),
  play: () => request('POST', '/replay/play'),

  detection: () => request('GET', '/config/detection'),
  patchDetection: (changes) => request('PATCH', '/config/detection', changes),
  resetDetection: () => request('DELETE', '/config/detection'),

  attacks: () => request('GET', '/attacks'),
  previewAttack: (lat, lon, radius_km) => request('GET', `/attacks/preview?${q({ lat, lon, radius_km })}`),
  createAttack: (body) => request('POST', '/attacks', body),
  patchAttack: (attackId, changes) => request('PATCH', `/attacks/${id(attackId)}`, changes),
  deleteAttack: (attackId) => request('DELETE', `/attacks/${id(attackId)}`),
  resetAttacks: () => request('DELETE', '/attacks'),

  incidents: () => request('GET', '/incidents'),
  incident: (incidentId) => request('GET', `/incidents/${id(incidentId)}`),
  reportUrl: (incidentId) => `${API_BASE}/api/incidents/${id(incidentId)}/report.pdf`,

  evaluation: () => request('GET', '/evaluation'),
  scenarios: () => request('GET', '/scenarios'),
  runScenario: (scenarioId) => request('POST', `/scenarios/${id(scenarioId)}/run`),

  sentinelLatest: () => request('GET', '/sentinel/latest'),
  sentinelHistory: (device = 'sentinel-1', minutes = 5) => request('GET', `/sentinel/history?${q({ id: device, minutes })}`),

  // {id, summary, source: 'ai'|'template', model, label, generated_ts, cached, facts}; 404 when the hexagon is gone.
  cellSummary: (h3) => request('GET', `/cells/${id(h3)}/summary`),
}

/** One readable sentence for a failed call. */
export function errorText(err) {
  if (!(err instanceof ApiError)) return String(err?.message || err)
  const d = err.detail
  if (Array.isArray(d)) {
    return d
      .map((e) => {
        const field = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body').join('.') : ''
        return field ? `${field}: ${e.msg}` : e.msg
      })
      .join('; ')
  }
  if (d && typeof d === 'object') return d.error || JSON.stringify(d)
  if (typeof d === 'string' && d) return d
  return `The backend answered HTTP ${err.status}.`
}
