import { useEffect } from 'react'
import { wsUrl } from '../config.js'
import { useStore } from '../store.js'
import { getTransport } from './client.js'

// One WebSocket for the whole picture (handover §4). The backend sends the
// newest tick on connect and then one per detector tick; we never send.
// Reconnects with backoff 1, 2, 4, 8, 10, 10 ... seconds.
export function useLiveFeed() {
  const setTick = useStore((s) => s.setTick)
  const setConnection = useStore((s) => s.setConnection)

  useEffect(() => {
    let ws = null
    let timer = null
    let attempt = 0
    let stopped = false

    const connect = () => {
      if (stopped) return
      setConnection({ state: attempt === 0 ? 'connecting' : 'reconnecting', attempt, retryAt: null })
      const Socket = getTransport().WebSocket
      try {
        ws = new Socket(wsUrl())
      } catch {
        scheduleRetry()
        return
      }
      ws.onopen = () => {
        attempt = 0
        setConnection({ state: 'open', attempt: 0, retryAt: null })
      }
      ws.onmessage = (ev) => {
        let msg
        try {
          msg = JSON.parse(ev.data)
        } catch {
          return
        }
        if (msg && msg.type === 'tick') setTick(msg)
      }
      ws.onerror = () => {
        try {
          ws.close()
        } catch {
          /* already closed */
        }
      }
      ws.onclose = () => {
        if (!stopped) scheduleRetry()
      }
    }

    const scheduleRetry = () => {
      const delay = Math.min(10000, 1000 * 2 ** attempt)
      attempt += 1
      setConnection({ state: 'reconnecting', attempt, retryAt: Date.now() + delay })
      window.clearTimeout(timer)
      timer = window.setTimeout(connect, delay)
    }

    connect()
    return () => {
      stopped = true
      window.clearTimeout(timer)
      if (ws) {
        ws.onclose = null
        try {
          ws.close()
        } catch {
          /* ignore */
        }
      }
    }
  }, [setTick, setConnection])
}
