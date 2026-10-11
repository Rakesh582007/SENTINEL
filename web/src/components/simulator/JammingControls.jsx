import { useEffect, useState } from 'react'
import { api, errorText } from '../../api/client.js'
import { fmtLatLon } from '../../lib/geo.js'
import { clock } from '../../lib/time.js'
import { useDerived, useStore } from '../../store.js'
import { Button, Slider } from '../ui.jsx'
import { useDebouncedCallback } from './useDebouncedCallback.js'

const PLACES = [
  { label: 'Delhi approach', center: [28.47, 77.2], note: 'busiest traffic' },
  { label: 'Amritsar', center: [31.63, 74.87], note: 'thin coverage' },
]

function toApi(patch) {
  const out = {}
  if ('radius_km' in patch) out.radius_km = patch.radius_km
  if ('strength' in patch) out.strength = patch.strength
  if ('position_loss' in patch) out.position_loss = patch.position_loss
  if ('duration_min' in patch) out.duration_s = patch.duration_min == null ? null : patch.duration_min * 60
  return out
}

function PreviewBox({ preview, loading }) {
  if (!preview) {
    return <p className="text-[13.5px] text-ink-600">{loading ? 'Checking traffic under the jammer…' : 'Traffic check appears here.'}</p>
  }
  const ok = preview.likely_detectable
  return (
    <div className={`rounded-md border p-2.5 ${ok ? 'border-[#2EAF6E] bg-[#2EAF6E14]' : 'border-[#E8A33C] bg-[#E8A33C1a]'}`} aria-live="polite">
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-[13.5px]">
        <dt className="text-ink-700">Aircraft under it now</dt>
        <dd className="text-right font-data text-ink-900 tnum">{preview.aircraft_now}</dd>
        <dt className="text-ink-700">Seen there, last 20 min</dt>
        <dd className="text-right font-data text-ink-900 tnum">{preview.aircraft_in_window}</dd>
        <dt className="text-ink-700">Busiest hexagon under it</dt>
        <dd className="text-right font-data text-ink-900 tnum">
          {preview.busiest_cell_aircraft} of {preview.min_aircraft_per_cell} needed
        </dd>
      </dl>
      <p className={`mt-1.5 text-[13.5px] font-semibold leading-snug ${ok ? 'text-[#16613A]' : 'text-[#7A4B05]'}`}>
        {ok
          ? 'Enough aircraft for the crowd method. A strong jammer turns the hexagon red within a tick or two; a weak one may stay amber.'
          : preview.hint || 'Too few aircraft per hexagon here for the crowd method.'}
      </p>
    </div>
  )
}

export default function JammingControls() {
  const tick = useStore((s) => s.tick)
  const jammer = useStore((s) => s.jammer)
  const setJammer = useStore((s) => s.setJammer)
  const resetJammer = useStore((s) => s.resetJammer)
  const preview = useStore((s) => s.jammerPreview)
  const setJammerPreview = useStore((s) => s.setJammerPreview)
  const focusOn = useStore((s) => s.focusOn)
  const toast = useStore((s) => s.toast)
  const d = useDerived()
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const attack = jammer.attackId ? d.attacks.find((a) => a.id === jammer.attackId) : null

  // The attack disappeared (Reset all, mode switch, removed elsewhere): back to a draft.
  // Only trust ticks that arrived well after we bound the attack.
  const tickRecvAt = useStore((s) => s.tickRecvAt)
  useEffect(() => {
    if (jammer.attackId && tick && !attack && tickRecvAt > (jammer.boundAt || 0) + 1500) resetJammer()
  }, [jammer.attackId, jammer.boundAt, tick, tickRecvAt, attack, resetJammer])

  // Traffic check while placing / dragging, and every ~10 s of data time.
  const lat = jammer.center?.[0]
  const lon = jammer.center?.[1]
  const tickBucket = tick ? Math.floor(tick.ts / 10) : 0
  useEffect(() => {
    if (lat == null) {
      setJammerPreview(null)
      return undefined
    }
    let cancelled = false
    setLoading(true)
    const t = window.setTimeout(async () => {
      try {
        const r = await api.previewAttack(lat.toFixed(4), lon.toFixed(4), jammer.radius_km)
        if (!cancelled) setJammerPreview(r)
      } catch {
        /* the next tick retries */
      } finally {
        if (!cancelled) setLoading(false)
      }
    }, 250)
    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [lat, lon, jammer.radius_km, tickBucket, setJammerPreview])

  const patchSoon = useDebouncedCallback(async (changes) => {
    const id = useStore.getState().jammer.attackId
    if (!id || !changes || !Object.keys(changes).length) return
    try {
      await api.patchAttack(id, changes)
    } catch (e) {
      toast(`Could not update ${id}: ${errorText(e)}`, 'error')
    }
  }, 300)

  const update = (patch) => {
    setJammer(patch)
    if (jammer.attackId) patchSoon(toApi(patch))
  }

  const run = async (fn) => {
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  const start = () =>
    run(async () => {
      const res = await api.createAttack({
        kind: 'jamming',
        center: [+jammer.center[0].toFixed(4), +jammer.center[1].toFixed(4)],
        radius_km: jammer.radius_km,
        strength: jammer.strength,
        position_loss: jammer.position_loss,
        duration_s: jammer.duration_min == null ? null : jammer.duration_min * 60,
      })
      setJammer({ attackId: res.attack_id, boundAt: performance.now() })
      toast(`${res.attack_id} started. Hexagons react within about 10 s${tick?.mode === 'replay' ? '; keep the replay playing' : ''}.`, 'ok')
    })

  const setActive = (active) =>
    run(async () => {
      await api.patchAttack(jammer.attackId, { active })
      toast(active ? `${jammer.attackId} switched on again.` : `${jammer.attackId} switched off. The area recovers as reports age out.`, 'ok')
    })

  const remove = () =>
    run(async () => {
      const id = jammer.attackId
      await api.deleteAttack(id)
      resetJammer()
      toast(`${id} removed. Its effect is undone at once.`, 'ok')
    })

  const placeAt = (center) => {
    setJammer({ center })
    focusOn({ center, zoom: 7 })
  }

  let status = null
  if (attack) {
    if (attack.live) status = attack.remaining_s == null ? 'Live until you switch it off.' : `Live, ${clock(attack.remaining_s)} left.`
    else if (!attack.active) status = 'Switched off. Hexagons recover as old reports age out of the 20-minute window.'
    else status = 'Ran for its full duration. Switch on to run it again.'
  }

  return (
    <section aria-labelledby="jam-title" className="space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="jam-title" className="text-[17px] font-bold text-ink-900">
          Jamming
        </h2>
        {jammer.attackId ? <span className="font-data text-[13px] text-ink-700">{jammer.attackId}</span> : null}
      </div>

      {!jammer.center ? (
        <div className="space-y-2">
          <p className="text-[14.5px] leading-snug text-ink-900">Click the map where the jammer should be, then drag it to move.</p>
          <div className="flex flex-wrap gap-2">
            {PLACES.map((p) => (
              <Button key={p.label} size="sm" onClick={() => placeAt(p.center)}>
                {p.label} <span className="font-normal text-ink-600">({p.note})</span>
              </Button>
            ))}
          </div>
        </div>
      ) : (
        <>
          <p className="text-[13.5px] text-ink-700">
            Centre <span className="font-data text-ink-900">{fmtLatLon(jammer.center[0], jammer.center[1])}</span>. Drag the marker to move it.
          </p>
          <PreviewBox preview={preview} loading={loading} />
          <Slider id="jam-radius" label="Radius" min={10} max={150} step={5} value={jammer.radius_km} onChange={(v) => update({ radius_km: v })} format={(v) => `${v} km`} signal={Boolean(jammer.attackId)} />
          <Slider
            id="jam-strength"
            label="Strength"
            min={0}
            max={100}
            step={5}
            value={Math.round(jammer.strength * 100)}
            onChange={(v) => update({ strength: v / 100 })}
            format={(v) => `${v}%`}
            hint="Share of aircraft inside that lose GPS integrity."
            signal={Boolean(jammer.attackId)}
          />
          <Slider
            id="jam-poslost"
            label="Position loss"
            min={0}
            max={100}
            step={5}
            value={Math.round(jammer.position_loss * 100)}
            onChange={(v) => update({ position_loss: v / 100 })}
            format={(v) => `${v}%`}
            hint="Of those, the share that stop reporting a position at all."
            signal={Boolean(jammer.attackId)}
          />
          <div className="space-y-1">
            <label className="flex items-center gap-2 text-[14px] font-medium text-ink-700">
              <input
                type="checkbox"
                className="accent-air-600"
                checked={jammer.duration_min == null}
                onChange={(e) => update({ duration_min: e.target.checked ? null : 10 })}
              />
              Runs until switched off
            </label>
            {jammer.duration_min != null ? (
              <Slider id="jam-duration" label="Duration" min={1} max={30} step={1} value={jammer.duration_min} onChange={(v) => update({ duration_min: v })} format={(v) => `${v} min`} signal={Boolean(jammer.attackId)} />
            ) : null}
          </div>

          {status ? <p className="rounded-md bg-sand-200 px-2.5 py-1.5 text-[13.5px] font-semibold text-ink-900">{status}</p> : null}

          <div className="flex flex-wrap gap-2">
            {!jammer.attackId ? (
              <>
                <Button variant="signal" size="lg" onClick={start} disabled={busy || !tick}>
                  Start test jammer
                </Button>
                <Button onClick={resetJammer} disabled={busy}>
                  Discard
                </Button>
              </>
            ) : (
              <>
                {attack?.live ? (
                  <Button onClick={() => setActive(false)} disabled={busy}>
                    Switch off
                  </Button>
                ) : (
                  <Button variant="signal" onClick={() => setActive(true)} disabled={busy}>
                    Switch on
                  </Button>
                )}
                <Button variant="danger" onClick={remove} disabled={busy}>
                  Remove
                </Button>
                <Button variant="ghost" onClick={resetJammer} disabled={busy} title="Keep it running and place another jammer">
                  Place another
                </Button>
              </>
            )}
          </div>
          {jammer.attackId ? (
            <p className="text-[12.5px] leading-snug text-ink-600">
              Switch off stops new interference and lets the area recover realistically. Remove undoes it completely and the map clears at once.
            </p>
          ) : null}
        </>
      )}
    </section>
  )
}
