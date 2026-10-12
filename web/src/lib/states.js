// Words and colours for everything the detectors can say. Colour is never the
// only signal: every place that shows a colour also shows `label`.

export const CELL_STATES = ['jammed', 'spoofing', 'degraded', 'clear', 'insufficient']

export const STATE = {
  jammed: {
    label: 'Jammed',
    color: '#E5484D',
    ink: '#8F1F23',
    fill: 0.42,
    words: 'Several different aircraft lost GPS integrity in this hexagon.',
  },
  spoofing: {
    label: 'Spoofing',
    color: '#9B5DE5',
    ink: '#5B2A9A',
    fill: 0.42,
    words: 'Aircraft here report positions that are physically impossible.',
  },
  degraded: {
    label: 'Degraded',
    color: '#E8A33C',
    ink: '#7A4B05',
    fill: 0.4,
    words: 'At least one aircraft reports weak GPS, not enough to call it jamming.',
  },
  clear: {
    label: 'Clear',
    color: '#2EAF6E',
    ink: '#16613A',
    fill: 0.12,
    words: 'Aircraft here report healthy GPS.',
  },
  insufficient: {
    label: 'Too few aircraft',
    color: '#6B7A90',
    ink: '#3E4A5C',
    fill: 0.07,
    words: 'Not enough different aircraft to decide.',
  },
}

export const stateOf = (s) => STATE[s] || STATE.insufficient

// detect/jamming.py bad_reason()
export const BAD_REASON = {
  low_nacp: 'Low position accuracy (NACp)',
  low_nic: 'Low integrity (NIC)',
  position_lost: 'Position lost, still transmitting',
  gps_lost_flag: 'Aggregator saw GPS loss',
}

export const BAD_SHORT = {
  low_nacp: 'Low NACp',
  low_nic: 'Low NIC',
  position_lost: 'Position lost',
  gps_lost_flag: 'GPS loss flag',
}

// detect/spoofing.py reason codes
export const SPOOF_REASON = {
  impossible_jump: 'Impossible position jump',
  colocation_cluster: 'Several aircraft at one spot',
  alt_offset_outlier: 'GPS altitude disagrees with peers',
  track_mismatch: 'Heading disagrees with movement',
  recovery_jump: 'Jump as GPS came back (not spoofing)',
}

// Codes that count as spoofing evidence (spoofing.SPOOF_REASONS); recovery_jump is info only.
export const SPOOF_EVIDENCE = new Set(['impossible_jump', 'colocation_cluster', 'alt_offset_outlier', 'track_mismatch'])

export const hasSpoofEvidence = (codes) => Array.isArray(codes) && codes.some((c) => SPOOF_EVIDENCE.has(c))

export const SENTINEL_STATUS = {
  OK: { label: 'OK', color: '#2EAF6E', ink: '#16613A', words: 'Satellite signal normal.' },
  SEARCHING: { label: 'Searching', color: '#7D8CA1', ink: '#3E4A5C', words: 'No satellite fix yet. Needs sky view.' },
  JAMMING: { label: 'Jamming', color: '#E5484D', ink: '#8F1F23', words: 'Signal dropped far below its baseline.' },
  SPOOF: { label: 'Spoof', color: '#9B5DE5', ink: '#5B2A9A', words: 'The fixed box appears to move.' },
  OFFLINE: { label: 'Offline', color: '#6B7A90', ink: '#3E4A5C', words: 'No packets from the box in the last 10 s.' },
}

export const sentinelOf = (s) => SENTINEL_STATUS[s] || { label: s || 'Unknown', color: '#6B7A90', ink: '#3E4A5C', words: '' }

export const INJECTED_LABEL = 'INJECTED TEST ATTACK'
