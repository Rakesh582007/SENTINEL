import { useStore } from '../../store.js'
import { useNow } from '../ui.jsx'

/** Seconds of *data* time since the newest tick arrived: wall time in live mode,
 *  wall time x speed in replay (0 while paused). Lets countdowns tick between ticks. */
export function useDataElapsed() {
  const tick = useStore((s) => s.tick)
  const recv = useStore((s) => s.tickRecvAt)
  useNow(1000)
  if (!tick || !recv) return 0
  const wall = Math.min(12, (performance.now() - recv) / 1000) // never run away if the feed stalls
  if (tick.mode === 'replay') {
    const r = tick.replay
    if (!r || r.paused || r.finished) return 0
    return wall * (r.speed || 1)
  }
  return wall
}
