// All times on screen are IST (handover §4: display ts + 5.5 h).
const opts = { timeZone: 'Asia/Kolkata', hourCycle: 'h23' }
const fmtHMS = new Intl.DateTimeFormat('en-GB', { ...opts, hour: '2-digit', minute: '2-digit', second: '2-digit' })
const fmtHM = new Intl.DateTimeFormat('en-GB', { ...opts, hour: '2-digit', minute: '2-digit' })
const fmtDay = new Intl.DateTimeFormat('en-GB', { ...opts, day: 'numeric', month: 'short' })

const valid = (ts) => typeof ts === 'number' && Number.isFinite(ts) && ts > 0

export const istTime = (ts) => (valid(ts) ? fmtHMS.format(new Date(ts * 1000)) : '--:--:--')
export const istHM = (ts) => (valid(ts) ? fmtHM.format(new Date(ts * 1000)) : '--:--')
export const istDay = (ts) => (valid(ts) ? fmtDay.format(new Date(ts * 1000)) : '')

/** "45 s", "8 min", "1 h 05 min" */
export function duration(s) {
  if (s == null || !Number.isFinite(s)) return '–'
  const v = Math.max(0, Math.round(s))
  if (v < 60) return `${v} s`
  const m = Math.round(v / 60)
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60)
  return `${h} h ${String(m % 60).padStart(2, '0')} min`
}

/** Countdown style "7:42" for ETAs and timers. */
export function clock(s) {
  if (s == null || !Number.isFinite(s)) return '–'
  const v = Math.max(0, Math.round(s))
  const m = Math.floor(v / 60)
  return `${m}:${String(v % 60).padStart(2, '0')}`
}

export function ago(s) {
  if (s == null || !Number.isFinite(s)) return '–'
  if (s < 1.5) return 'just now'
  return `${duration(s)} ago`
}
