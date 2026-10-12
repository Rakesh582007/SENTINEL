import { useEffect, useMemo, useRef } from 'react'

/** Calls fn(lastArgs) once input has been quiet for `ms`. Merges object arguments,
 *  so several slider moves in a burst become one PATCH with every field. */
export function useDebouncedCallback(fn, ms = 300) {
  const fnRef = useRef(fn)
  fnRef.current = fn
  const state = useRef({ timer: null, pending: null })

  useEffect(() => () => window.clearTimeout(state.current.timer), [])

  return useMemo(
    () => (arg) => {
      const s = state.current
      s.pending = arg && typeof arg === 'object' && !Array.isArray(arg) ? { ...(s.pending || {}), ...arg } : arg
      window.clearTimeout(s.timer)
      s.timer = window.setTimeout(() => {
        const payload = s.pending
        s.pending = null
        fnRef.current(payload)
      }, ms)
    },
    [ms],
  )
}
