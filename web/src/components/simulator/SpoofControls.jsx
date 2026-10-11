import { useEffect, useState } from 'react'
import { api, errorText } from '../../api/client.js'
import { useDerived, useStore } from '../../store.js'
import { Button, Slider } from '../ui.jsx'

function Compass({ deg }) {
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true" className="shrink-0">
      <circle cx="17" cy="17" r="15" fill="#FBF8F1" stroke="#C8B78F" strokeWidth="1.5" />
      <text x="17" y="8.5" textAnchor="middle" fontSize="7" fill="#4B5E78" fontFamily="B612, Consolas, monospace">
        N
      </text>
      <g transform={`rotate(${deg} 17 17)`}>
        <path d="M17 6 L21 17 L17 15 L13 17 Z" fill="#B4470C" />
        <path d="M17 17 L17 27" stroke="#B4470C" strokeWidth="1.6" />
      </g>
    </svg>
  )
}

const compassWord = (deg) => ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'][Math.round(((deg % 360) + 360) % 360 / 45) % 8]

export default function SpoofControls() {
  const spoof = useStore((s) => s.spoof)
  const setSpoof = useStore((s) => s.setSpoof)
  const picking = useStore((s) => s.picking)
  const setPicking = useStore((s) => s.setPicking)
  const toast = useStore((s) => s.toast)
  const tick = useStore((s) => s.tick)
  const d = useDerived()
  const [busy, setBusy] = useState(false)
  const target = spoof.target !== 'random' ? d.aircraftByHex.get(spoof.target) : null

  useEffect(() => {
    if (!picking) return undefined
    const onKey = (e) => e.key === 'Escape' && setPicking(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [picking, setPicking])

  const go = async () => {
    setBusy(true)
    try {
      const res = await api.createAttack({
        kind: 'spoof',
        hex: spoof.target,
        offset_km: spoof.offset_km,
        bearing_deg: spoof.bearing_deg,
        alt_offset_ft: spoof.alt_offset_ft,
        duration_s: spoof.duration_min * 60,
      })
      const hex = res.attack?.hex
      const ac = hex ? d.aircraftByHex.get(hex) : null
      const who = ac?.flight || hex?.toUpperCase() || 'an aircraft'
      toast(
        spoof.offset_km > 5
          ? `${res.attack_id} moves ${who}'s reported position from its next report (usually 10 to 30 s). Its hexagon then turns purple.`
          : `${res.attack_id} changes ${who}'s GPS altitude only. That flags the aircraft, not the hexagon.`,
        'ok',
      )
    } catch (e) {
      toast(e?.status === 409 ? 'No airborne aircraft to spoof right now. Wait for traffic, or pick one on the map.' : `Could not spoof: ${errorText(e)}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-labelledby="spoof-title" className="space-y-3">
      <h2 id="spoof-title" className="text-[17px] font-bold text-ink-900">
        Spoofing
      </h2>
      <p className="text-[14px] leading-snug text-ink-700">Feed one aircraft a false position, the way a spoofer would. Its own GPS scores stay perfect.</p>

      <div className="space-y-2">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Target aircraft">
          <Button
            size="sm"
            variant={picking ? 'primary' : 'quiet'}
            aria-pressed={picking}
            onClick={() => setPicking(!picking)}
          >
            {picking ? 'Click an aircraft on the map…' : 'Pick on the map'}
          </Button>
          <Button size="sm" variant={spoof.target === 'random' ? 'primary' : 'quiet'} aria-pressed={spoof.target === 'random'} onClick={() => setSpoof({ target: 'random' })}>
            Random aircraft
          </Button>
        </div>
        <p className="text-[13.5px] text-ink-700">
          Target:{' '}
          {spoof.target === 'random' ? (
            <span className="font-semibold">a random airborne aircraft</span>
          ) : (
            <>
              <span className="font-data font-bold text-ink-900">{target?.flight || spoof.target.toUpperCase()}</span>
              {target ? (
                <span className="text-ink-600"> at {target.alt_baro != null ? `${target.alt_baro.toLocaleString('en-IN')} ft` : 'unknown altitude'}</span>
              ) : (
                <span className="text-[#8F1F23]"> (not in view right now)</span>
              )}
            </>
          )}
        </p>
      </div>

      <Slider id="sp-offset" label="Position offset" min={0} max={80} step={1} value={spoof.offset_km} onChange={(v) => setSpoof({ offset_km: v })} format={(v) => `${v} km`} />
      <div className="flex items-end gap-3">
        <div className="min-w-0 flex-1">
          <Slider
            id="sp-bearing"
            label="Direction"
            min={0}
            max={359}
            step={1}
            value={spoof.bearing_deg}
            onChange={(v) => setSpoof({ bearing_deg: v })}
            format={(v) => `${v}°, ${compassWord(v)}`}
          />
        </div>
        <Compass deg={spoof.bearing_deg} />
      </div>
      <Slider
        id="sp-alt"
        label="GPS altitude offset"
        min={-4000}
        max={4000}
        step={100}
        value={spoof.alt_offset_ft}
        onChange={(v) => setSpoof({ alt_offset_ft: v })}
        format={(v) => `${v > 0 ? '+' : ''}${v.toLocaleString('en-IN')} ft`}
        hint="An altitude-only spoof flags the aircraft but not its hexagon: one aircraft with weak evidence is not enough."
      />
      <Slider id="sp-dur" label="Duration" min={1} max={30} step={1} value={spoof.duration_min} onChange={(v) => setSpoof({ duration_min: v })} format={(v) => `${v} min`} />
      <Button variant="signal" size="lg" onClick={go} disabled={busy || !tick || (spoof.offset_km === 0 && spoof.alt_offset_ft === 0)}>
        Spoof now
      </Button>
      {spoof.offset_km === 0 && spoof.alt_offset_ft === 0 ? <p className="text-[12.5px] text-ink-600">Set an offset first: with both at zero nothing changes.</p> : null}
    </section>
  )
}
