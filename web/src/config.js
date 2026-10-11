// Runtime settings. In normal use the Vite dev server proxies /api and /ws to
// the FastAPI backend (see vite.config.js), so relative URLs are enough.
// Set VITE_API_BASE (e.g. http://192.168.1.20:8000) only if you serve the
// built files from somewhere that has no proxy; the backend's CORS list must
// then include that origin.

/* global __STANDALONE__ */
export const STANDALONE = typeof __STANDALONE__ !== 'undefined' && __STANDALONE__

export const API_BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

export function wsUrl() {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL
  if (API_BASE) return API_BASE.replace(/^http/, 'ws') + '/ws'
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws`
}

export const TICK_S = 5 // backend detector tick (settings.tick_s)
export const STALE_AFTER_S = 16 // no tick for this long = show a warning
export const DEFAULT_VIEW = { center: [30.5, 75.5], zoom: 6 } // Delhi, Punjab, J&K and Islamabad in view
