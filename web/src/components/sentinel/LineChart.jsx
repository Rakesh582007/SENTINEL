import { useEffect, useMemo, useRef, useState } from 'react'
import { istTime } from '../../lib/time.js'

function useWidth() {
  const ref = useRef(null)
  const [w, setW] = useState(480)
  useEffect(() => {
    if (!ref.current || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.round(e.contentRect.width))))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

function niceTicks(lo, hi, count = 4) {
  const span = Math.max(1e-6, hi - lo)
  const raw = span / count
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || raw
  const out = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6))
  return out
}

/**
 * One series over the last `windowS` seconds. Thin 2 px line, end dot with its
 * value, hairline grid, optional reference lines (dashed: they are thresholds,
 * not grid). No area fill: the y axis does not start at zero. Hover shows a
 * crosshair readout; a screen-reader table carries the same values.
 */
export default function LineChart({ points, now, windowS = 300, unit = '', yDomain, refs = [], height = 170, step = false, label, decimals = 1 }) {
  const [box, width] = useWidth()
  const [hover, setHover] = useState(null)
  const pad = { l: 40, r: 52, t: 14, b: 26 }
  const iw = Math.max(10, width - pad.l - pad.r)
  const ih = height - pad.t - pad.b
  const t0 = now - windowS

  const visible = useMemo(() => points.filter((p) => p.t >= t0 - 5 && p.v != null && Number.isFinite(p.v)), [points, t0])
  const vals = visible.map((p) => p.v).concat(refs.map((r) => r.value).filter((v) => v != null))
  let [lo, hi] = yDomain || [Math.min(...vals, Infinity), Math.max(...vals, -Infinity)]
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) [lo, hi] = [0, 1]
  if (!yDomain) {
    const m = Math.max(1, (hi - lo) * 0.15)
    lo = Math.floor(lo - m)
    hi = Math.ceil(hi + m)
  }
  const x = (t) => pad.l + ((t - t0) / windowS) * iw
  const y = (v) => pad.t + ih - ((v - lo) / Math.max(1e-6, hi - lo)) * ih
  const ticks = niceTicks(lo, hi, 4)

  let d = ''
  visible.forEach((p, i) => {
    const px = x(Math.max(t0, p.t)).toFixed(1)
    const py = y(p.v).toFixed(1)
    if (i === 0) d += `M${px} ${py}`
    else if (step) d += `H${px}V${py}`
    else d += `L${px} ${py}`
  })
  const last = visible[visible.length - 1]

  const onMove = (e) => {
    if (!visible.length) return
    const rect = e.currentTarget.getBoundingClientRect()
    const t = t0 + ((e.clientX - rect.left - pad.l) / iw) * windowS
    let best = visible[0]
    for (const p of visible) if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p
    setHover(best)
  }

  const fmt = (v) => (v == null ? '–' : `${v.toFixed(decimals)}${unit ? ` ${unit}` : ''}`)

  return (
    <div ref={box} className="relative w-full">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`${label}: ${last ? fmt(last.v) : 'no data'} now`}
        className="block touch-none select-none"
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={pad.l + iw} y1={y(v)} y2={y(v)} stroke="#E1D5B8" strokeWidth="1" />
            <text x={pad.l - 6} y={y(v)} dy="0.32em" textAnchor="end" fontSize="11" fill="#4B5E78" className="tnum" fontFamily="B612, Consolas, monospace">
              {v}
            </text>
          </g>
        ))}
        {[0, 60, 120, 180, 240, 300]
          .filter((s) => s <= windowS)
          .map((s) => (
            <text key={s} x={x(now - windowS + s)} y={height - 8} textAnchor="middle" fontSize="11" fill="#4B5E78">
              {s === windowS ? 'now' : `−${(windowS - s) / 60} min`}
            </text>
          ))}
        {refs.map((r) =>
          r.value == null ? null : (
            <g key={r.label}>
              <line x1={pad.l} x2={pad.l + iw} y1={y(r.value)} y2={y(r.value)} stroke={r.color} strokeWidth="1.5" strokeDasharray="5 4" />
              <text x={pad.l + 6} y={y(r.value) - 4} fontSize="11" fill={r.ink || r.color}>
                {r.label}
              </text>
            </g>
          ),
        )}
        {d ? <path d={d} fill="none" stroke="#1E5AA8" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" /> : null}
        {last ? (
          <>
            <circle cx={x(last.t)} cy={y(last.v)} r="4.5" fill="#1E5AA8" stroke="#F6F1E5" strokeWidth="2" />
            <text x={x(last.t) + 8} y={y(last.v)} dy="0.32em" fontSize="12.5" fontWeight="700" fill="#13294B" fontFamily="B612, Consolas, monospace">
              {last.v.toFixed(decimals)}
            </text>
          </>
        ) : (
          <text x={pad.l + iw / 2} y={pad.t + ih / 2} textAnchor="middle" fontSize="13" fill="#4B5E78">
            No packets in the last {Math.round(windowS / 60)} minutes
          </text>
        )}
        {hover ? (
          <g pointerEvents="none">
            <line x1={x(hover.t)} x2={x(hover.t)} y1={pad.t} y2={pad.t + ih} stroke="#7D8CA1" strokeWidth="1" />
            <circle cx={x(hover.t)} cy={y(hover.v)} r="4" fill="#1E5AA8" stroke="#F6F1E5" strokeWidth="2" />
          </g>
        ) : null}
      </svg>
      {hover ? (
        <div
          className="pointer-events-none absolute top-1 rounded-md border border-sand-400 bg-sand-50 px-2 py-1 text-[12.5px] shadow-float"
          style={{ left: Math.min(width - 150, Math.max(0, x(hover.t) - 70)) }}
        >
          <div className="font-data text-[14px] font-bold text-ink-900 tnum">{fmt(hover.v)}</div>
          <div className="text-ink-600">{istTime(hover.t)} IST</div>
        </div>
      ) : null}
      <table className="sr-only">
        <caption>{label}, last {Math.round(windowS / 60)} minutes</caption>
        <tbody>
          {visible.slice(-30).map((p) => (
            <tr key={p.t}>
              <td>{istTime(p.t)}</td>
              <td>{fmt(p.v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
