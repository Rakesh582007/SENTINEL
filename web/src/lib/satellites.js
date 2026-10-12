// Satellite names and signal quality bands for the Ground Sentinel.

// C/N0 bands in dB-Hz. Common GNSS rule of thumb; colour is always paired with the word.
export const STRONG_DB = 35
export const MEDIUM_DB = 28

export const SIGNAL = {
  strong: { label: 'Strong', color: '#2EAF6E', ink: '#16613A' },
  medium: { label: 'Medium', color: '#E8A33C', ink: '#7A4B05' },
  weak: { label: 'Weak', color: '#E5484D', ink: '#8F1F23' },
}

export function signalBand(db) {
  if (typeof db !== 'number' || !Number.isFinite(db)) return SIGNAL.weak
  if (db >= STRONG_DB) return SIGNAL.strong
  if (db >= MEDIUM_DB) return SIGNAL.medium
  return SIGNAL.weak
}

const PREFIX = { G: 'GPS', R: 'GLONASS', E: 'Galileo', C: 'BeiDou', J: 'QZSS', S: 'SBAS' }

/** "GPS G12" from "G12" or from an NMEA PRN number (1-32 GPS, 65-96 GLONASS, 201-237 BeiDou, 301-336 Galileo). */
export function satName(id, index) {
  if (typeof id === 'string' && /^[GRECJS]\d{1,3}$/i.test(id.trim())) {
    const code = id.trim().toUpperCase()
    return `${PREFIX[code[0]]} ${code}`
  }
  const n = Number(id)
  if (Number.isFinite(n) && id !== null && id !== '') {
    const pad = (v) => String(v).padStart(2, '0')
    if (n >= 1 && n <= 32) return `GPS G${pad(n)}`
    if (n >= 65 && n <= 96) return `GLONASS R${pad(n - 64)}`
    if (n >= 201 && n <= 237) return `BeiDou C${pad(n - 200)}`
    if (n >= 301 && n <= 336) return `Galileo E${pad(n - 300)}`
    return `Satellite ${n}`
  }
  return `Satellite ${index + 1}`
}

// Example satellites for the manual Attack mode (the healthy level of each).
export const SIM_SATS = [
  { id: 'G05', base: 44 },
  { id: 'G12', base: 43 },
  { id: 'G25', base: 41 },
  { id: 'E11', base: 40 },
  { id: 'E24', base: 40 },
  { id: 'R07', base: 39 },
  { id: 'R18', base: 38 },
  { id: 'C21', base: 38 },
  { id: 'C34', base: 36 },
].map((s) => ({ ...s, name: satName(s.id) }))
