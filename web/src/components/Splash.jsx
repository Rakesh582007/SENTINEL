import { useEffect, useMemo, useRef, useState } from 'react'

// Intro: you stand at a runway threshold looking down the approach lights, an
// airliner waiting on the horizon. "Enter dashboard" (or Enter) sends it at you
// and over your head, then the dashboard opens. "Skip intro" (or Esc) goes
// straight in. Reduced motion: no flight. No password: a localhost demo has
// nothing to protect; "Log out" in the top bar brings you back here.

const HORIZON = 600 // viewBox is 1600 x 900
const FOCAL = 4500 // perspective scale, px per metre at 1 m
const EYE_M = 2

const yAt = (d) => HORIZON + (FOCAL * EYE_M) / d
const halfWidthAt = (d, metres) => (FOCAL * metres) / d

function ApproachLights() {
  const bars = useMemo(() => {
    const out = []
    for (let d = 45; d <= 900; d += 30) out.push(d)
    return out
  }, [])
  return (
    <g>
      {bars.map((d) => {
        const y = yAt(d)
        const hw = halfWidthAt(d, 1.5)
        const r = Math.max(1.1, 260 / d)
        return (
          <g key={d}>
            {[-2, -1, 0, 1, 2].map((k) => (
              <g key={k}>
                <circle cx={800 + (k * hw) / 2} cy={y} r={r * 3.2} fill="url(#lightGlow)" />
                <circle cx={800 + (k * hw) / 2} cy={y} r={r} fill="#FFFBEA" />
              </g>
            ))}
            {d > 300 && (
              <circle
                className="rabbit"
                style={{ animationDelay: `${(((900 - d) / 600) * 0.55).toFixed(3)}s` }}
                cx={800}
                cy={y}
                r={r * 2.6}
                fill="#FFFFFF"
              />
            )}
          </g>
        )
      })}
      {/* 300 m crossbar */}
      {Array.from({ length: 21 }, (_, i) => i - 10).map((k) => {
        const d = 300
        const x = 800 + (k * halfWidthAt(d, 15)) / 10
        return <circle key={k} cx={x} cy={yAt(d)} r={1.6} fill="#FFFBEA" />
      })}
    </g>
  )
}

// Head-on airliner, drawn around (0, 0), wingspan 600 units.
function Airliner() {
  const ink = '#13294B'
  const body = '#F4F7FA'
  return (
    <g strokeLinejoin="round" strokeLinecap="round">
      {/* landing-light glow, behind everything */}
      <circle cx="-52" cy="12" r="70" fill="url(#landingGlow)" />
      <circle cx="52" cy="12" r="70" fill="url(#landingGlow)" />
      {/* vertical fin, seen edge-on */}
      <path d="M-5 -30 L-3 -128 L3 -128 L5 -30 Z" fill={body} stroke={ink} strokeWidth="2.2" />
      {/* tailplane */}
      <path d="M-14 -24 L-112 -40 L-112 -35 L-14 -16 Z" fill={body} stroke={ink} strokeWidth="2" />
      <path d="M14 -24 L112 -40 L112 -35 L14 -16 Z" fill={body} stroke={ink} strokeWidth="2" />
      {/* wings with dihedral and winglets */}
      <path d="M-30 2 L-298 -26 L-300 -20 L-30 15 Z" fill={body} stroke={ink} strokeWidth="2.2" />
      <path d="M30 2 L298 -26 L300 -20 L30 15 Z" fill={body} stroke={ink} strokeWidth="2.2" />
      <path d="M-299 -24 L-306 -58 L-301 -59 L-296 -25 Z" fill={body} stroke={ink} strokeWidth="1.8" />
      <path d="M299 -24 L306 -58 L301 -59 L296 -25 Z" fill={body} stroke={ink} strokeWidth="1.8" />
      {/* pylons + engines */}
      {[-1, 1].map((s) => (
        <g key={s}>
          <path d={`M${s * 100} 2 L${s * 108} 2 L${s * 108} 14 L${s * 100} 14 Z`} fill={body} stroke={ink} strokeWidth="1.6" />
          <circle cx={s * 104} cy="30" r="23" fill="#E6EBF1" stroke={ink} strokeWidth="2.2" />
          <circle cx={s * 104} cy="30" r="15.5" fill="#22344F" />
          <circle cx={s * 104} cy="30" r="4.5" fill="#C9D2DD" />
        </g>
      ))}
      {/* landing gear */}
      {[-40, 40].map((x) => (
        <g key={x}>
          <path d={`M${x} 14 L${x} 58`} stroke={ink} strokeWidth="3" />
          <rect x={x - 9} y="56" width="7" height="13" rx="2" fill="#22344F" />
          <rect x={x + 2} y="56" width="7" height="13" rx="2" fill="#22344F" />
        </g>
      ))}
      <path d="M0 34 L0 60" stroke={ink} strokeWidth="2.6" />
      <rect x="-6" y="58" width="12" height="11" rx="2" fill="#22344F" />
      {/* fuselage */}
      <circle cx="0" cy="0" r="35" fill={body} stroke={ink} strokeWidth="2.4" />
      <path d="M-25 -9 Q0 -20 25 -9 L22 -2 Q0 -11 -22 -2 Z" fill="#1D3557" />
      <path d="M-8 -16 L-6 -6 M8 -16 L6 -6" stroke={body} strokeWidth="2" />
      {/* lights */}
      <circle cx="-52" cy="12" r="5" fill="#FFF6D0" />
      <circle cx="52" cy="12" r="5" fill="#FFF6D0" />
      <circle cx="0" cy="40" r="3.2" fill="#FFF6D0" />
    </g>
  )
}

export default function Splash({ onEnter }) {
  // idle: title + button, plane waiting low on the horizon
  // flying: the plane comes at you and passes overhead, then the dashboard opens
  const [phase, setPhase] = useState('idle')
  const buttonRef = useRef(null)
  const reduced = useMemo(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches, [])

  const fly = () => {
    if (phase !== 'idle') return
    if (reduced) {
      setPhase('leaving')
      window.setTimeout(onEnter, 150)
      return
    }
    setPhase('flying')
    window.setTimeout(() => setPhase('leaving'), 2350)
    window.setTimeout(onEnter, 2800)
  }

  const skip = () => {
    if (phase === 'leaving') return
    setPhase('leaving')
    window.setTimeout(onEnter, 150)
  }

  useEffect(() => {
    buttonRef.current?.focus({ preventScroll: true })
  }, [])

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Enter') {
        e.preventDefault()
        fly()
      } else if (e.key === 'Escape') {
        e.preventDefault()
        skip()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <div
      className={`splash fixed inset-0 z-[2000] overflow-hidden bg-air-100 ${phase === 'flying' || phase === 'leaving' ? 'splash-flying' : ''} ${phase === 'leaving' ? 'splash-leaving' : ''}`}
      role="dialog"
      aria-modal="true"
      aria-label="SENTINEL intro"
    >
      <svg className="splash-scene absolute inset-0 h-full w-full" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
        <defs>
          <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#B7D2EA" />
            <stop offset="1" stopColor="#E9F1F8" />
          </linearGradient>
          <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#E3D8BD" />
            <stop offset="1" stopColor="#D6C7A2" />
          </linearGradient>
          <radialGradient id="lightGlow">
            <stop offset="0" stopColor="#FFF4C2" stopOpacity="0.85" />
            <stop offset="1" stopColor="#FFF4C2" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="landingGlow">
            <stop offset="0" stopColor="#FFF8DC" stopOpacity="0.95" />
            <stop offset="0.35" stopColor="#FFF1C0" stopOpacity="0.45" />
            <stop offset="1" stopColor="#FFF1C0" stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect width="1600" height={HORIZON} fill="url(#sky)" />
        <path
          d={`M0 ${HORIZON} L0 588 C120 580 210 592 330 586 C470 579 560 594 700 589 C820 585 930 593 1060 586 C1190 579 1300 591 1440 584 C1520 581 1570 586 1600 584 L1600 ${HORIZON} Z`}
          fill="#D2C8B0"
        />
        <rect y={HORIZON} width="1600" height={900 - HORIZON} fill="url(#ground)" />
        <path d={`M770 ${HORIZON} L830 ${HORIZON} L1130 900 L470 900 Z`} fill="#CBBE9C" opacity="0.55" />
        <ApproachLights />
        <g className="plane-fly">
          <Airliner />
        </g>
      </svg>

      <button
        type="button"
        onClick={skip}
        className="absolute right-4 top-4 rounded-md px-3 py-1.5 text-sm font-medium text-ink-700 underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-air-600"
        style={{ top: 'calc(env(safe-area-inset-top, 0px) + 16px)' }}
      >
        Skip intro
      </button>

      <div className="splash-title absolute inset-x-0 top-[13%] flex flex-col items-center px-4 text-center">
        <h1 className="font-data text-[clamp(44px,8vw,96px)] font-bold leading-none tracking-[0.22em] text-ink-900 [text-wrap:balance]" style={{ marginRight: '-0.22em' }}>
          SENTINEL
        </h1>
        <p className="mt-3 text-[clamp(18px,2.2vw,26px)] font-medium text-ink-700">GPS Attack Watch</p>
        <p className="mt-4 max-w-[34rem] text-[17px] leading-relaxed text-ink-600 [text-wrap:balance]">
          Live warning of GPS jamming and spoofing over Indian airspace, read from the signals aircraft already broadcast.
        </p>
        <button
          ref={buttonRef}
          type="button"
          onClick={fly}
          disabled={phase !== 'idle'}
          className="mt-7 rounded-lg bg-air-600 px-7 py-3 text-lg font-semibold text-white shadow-float transition-colors hover:bg-air-700 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-air-800"
        >
          Enter dashboard
        </button>
        <p className="mt-5 text-sm text-ink-600">Team Ethicals, SEDHACKS&apos;26. Receive-only: nothing in this system transmits.</p>
      </div>
    </div>
  )
}
