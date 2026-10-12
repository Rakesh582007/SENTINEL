import { useEffect, useState } from 'react'
import { INJECTED_LABEL, sentinelOf, stateOf } from '../lib/states.js'

/** Orange badge on anything a simulated attack produced (hard rule, handover §9). */
export function InjectedBadge({ className = '', short = false }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded px-1.5 py-px font-data text-[10.5px] font-bold leading-[1.5] tracking-[0.04em] text-signal-900 ${className}`}
      style={{ background: '#F26B1D' }}
      title="Simulated in the Attack Simulator. Not a real-world event."
    >
      {short ? 'INJECTED' : INJECTED_LABEL}
    </span>
  )
}

/** Colour swatch + word. Colour is never shown without the word. */
export function StateChip({ state, size = 'md', className = '' }) {
  const s = stateOf(state)
  const big = size === 'lg'
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border font-semibold ${big ? 'px-2.5 py-1 text-[15px]' : 'px-2 py-0.5 text-[13px]'} ${className}`}
      style={{ borderColor: s.color, color: s.ink, background: `${s.color}1f` }}
    >
      <span className="inline-block rounded-sm" style={{ width: big ? 12 : 10, height: big ? 12 : 10, background: s.color }} aria-hidden="true" />
      {s.label}
    </span>
  )
}

export function SentinelChip({ status, className = '' }) {
  const s = sentinelOf(status)
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[13px] font-semibold ${className}`}
      style={{ borderColor: s.color, color: s.ink, background: `${s.color}1f` }}
    >
      <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: s.color }} aria-hidden="true" />
      {s.label}
    </span>
  )
}

const BUTTON = {
  primary: 'bg-air-600 text-white hover:bg-air-700 border border-air-600',
  signal: 'bg-signal-500 text-signal-900 hover:bg-[#e05d12] border border-signal-500',
  quiet: 'bg-sand-50 text-ink-900 hover:bg-air-50 border border-sand-400',
  danger: 'bg-sand-50 text-[#8F1F23] hover:bg-[#fdecec] border border-[#E5484D]',
  ghost: 'bg-transparent text-air-700 hover:bg-air-50 border border-transparent',
}

export function Button({ variant = 'quiet', size = 'md', className = '', ...props }) {
  const sz = size === 'sm' ? 'px-2.5 py-1 text-[13px]' : size === 'lg' ? 'px-4 py-2.5 text-[16px]' : 'px-3 py-1.5 text-[14px]'
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-1.5 rounded-md font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${sz} ${BUTTON[variant]} ${className}`}
      {...props}
    />
  )
}

/** Re-render every `ms` (countdowns, "3 s ago"). */
export function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), ms)
    return () => window.clearInterval(t)
  }, [ms])
  return now
}

export function SectionTitle({ children, aside, className = '' }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 ${className}`}>
      <h2 className="text-[17px] font-bold text-ink-900">{children}</h2>
      {aside ? <div className="text-[13px] text-ink-600">{aside}</div> : null}
    </div>
  )
}

/** Label / value row for detail views. */
export function Fact({ label, children, mono = false }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-sand-300 py-1.5 last:border-b-0">
      <dt className="text-[14px] text-ink-600">{label}</dt>
      <dd className={`text-right text-[14px] font-semibold text-ink-900 ${mono ? 'font-data tnum font-normal' : ''}`}>{children}</dd>
    </div>
  )
}

export function Slider({ id, label, value, min, max, step = 1, onChange, format = (v) => v, hint, signal = false, disabled = false }) {
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-[14px] font-medium text-ink-700">
          {label}
        </label>
        <output htmlFor={id} className="font-data text-[13px] text-ink-900 tnum">
          {format(value)}
        </output>
      </div>
      <input
        id={id}
        type="range"
        className={`w-full ${signal ? 'signal' : ''}`}
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {hint ? <p className="text-[12.5px] leading-snug text-ink-600">{hint}</p> : null}
    </div>
  )
}
