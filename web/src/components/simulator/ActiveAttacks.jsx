import { useState } from 'react'
import { api, errorText } from '../../api/client.js'
import { fmtLatLon } from '../../lib/geo.js'
import { clock } from '../../lib/time.js'
import { useDerived, useStore } from '../../store.js'
import { Button, InjectedBadge } from '../ui.jsx'

function statusOf(a) {
  if (a.live) return a.remaining_s == null ? 'Live, until switched off' : `Live, ${clock(a.remaining_s)} left`
  if (!a.active) return 'Switched off'
  return 'Finished'
}

export default function ActiveAttacks() {
  const d = useDerived()
  const jammer = useStore((s) => s.jammer)
  const setJammer = useStore((s) => s.setJammer)
  const resetJammer = useStore((s) => s.resetJammer)
  const focusOn = useStore((s) => s.focusOn)
  const toast = useStore((s) => s.toast)
  const [busy, setBusy] = useState(null)

  const act = async (key, fn, ok) => {
    setBusy(key)
    try {
      await fn()
      if (ok) toast(ok, 'ok')
    } catch (e) {
      toast(errorText(e), 'error')
    } finally {
      setBusy(null)
    }
  }

  const edit = (a) => {
    setJammer({
      center: a.center,
      radius_km: a.radius_km,
      strength: a.strength,
      position_loss: a.position_loss,
      duration_min: a.duration_s == null ? null : Math.max(1, Math.round(a.duration_s / 60)),
      attackId: a.id,
      boundAt: performance.now(),
    })
    focusOn({ center: a.center, zoom: 7 })
  }

  const attacks = d.attacks
  return (
    <section aria-labelledby="active-title" className="space-y-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="active-title" className="text-[17px] font-bold text-ink-900">
          Active attacks
        </h2>
        <Button
          size="sm"
          variant="danger"
          disabled={!attacks.length || busy === 'reset'}
          onClick={() =>
            act(
              'reset',
              async () => {
                await api.resetAttacks()
                resetJammer()
              },
              'All simulated attacks removed. The map is back to recorded data only.',
            )
          }
        >
          Reset all
        </Button>
      </div>
      {attacks.length ? (
        <ul className="space-y-2">
          {attacks.map((a) => {
            const ac = a.kind === 'spoof' ? d.aircraftByHex.get(a.hex) : null
            const editing = jammer.attackId === a.id
            return (
              <li key={a.id} className={`rounded-lg border bg-sand-50 p-2.5 ${editing ? 'border-air-600' : 'border-sand-400'}`}>
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-data text-[13px] font-bold text-ink-900">{a.id}</span>
                  <span className="text-[14px] font-semibold text-ink-900">{a.kind === 'jamming' ? 'Jamming' : 'Spoofing'}</span>
                  <InjectedBadge />
                </div>
                <p className="mt-1 text-[13.5px] leading-snug text-ink-700">
                  {a.kind === 'jamming' ? (
                    <>
                      <span className="font-data">{fmtLatLon(a.center[0], a.center[1])}</span>, {Math.round(a.radius_km)} km, strength {Math.round(a.strength * 100)}%, position loss{' '}
                      {Math.round(a.position_loss * 100)}%. Up to {a.max_aircraft_inside} aircraft inside so far.
                    </>
                  ) : (
                    <>
                      {ac?.flight || a.hex?.toUpperCase()}: position moved {Math.round(a.offset_km)} km toward {Math.round(a.bearing_deg)}°
                      {a.alt_offset_ft ? `, GPS altitude ${a.alt_offset_ft > 0 ? '+' : ''}${Math.round(a.alt_offset_ft)} ft` : ''}
                      {ac ? '' : ' (aircraft no longer in view)'}.
                    </>
                  )}
                </p>
                <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                  <span className={`text-[13px] font-semibold ${a.live ? 'text-[#B4470C]' : 'text-ink-600'}`}>{statusOf(a)}</span>
                  <span className="flex flex-wrap gap-1.5">
                    {a.kind === 'jamming' && !editing ? (
                      <Button size="sm" onClick={() => edit(a)}>
                        Edit
                      </Button>
                    ) : null}
                    {a.kind === 'spoof' && ac ? (
                      <Button size="sm" onClick={() => focusOn({ center: [ac.lat, ac.lon], zoom: 8 })}>
                        Show
                      </Button>
                    ) : null}
                    {a.live ? (
                      <Button size="sm" disabled={busy === a.id} onClick={() => act(a.id, () => api.patchAttack(a.id, { active: false }), `${a.id} switched off.`)}>
                        Switch off
                      </Button>
                    ) : (
                      <Button size="sm" variant="signal" disabled={busy === a.id} onClick={() => act(a.id, () => api.patchAttack(a.id, { active: true }), `${a.id} switched on.`)}>
                        Switch on
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={busy === a.id}
                      onClick={() =>
                        act(
                          a.id,
                          async () => {
                            await api.deleteAttack(a.id)
                            if (jammer.attackId === a.id) resetJammer()
                          },
                          `${a.id} removed.`,
                        )
                      }
                    >
                      Remove
                    </Button>
                  </span>
                </div>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="text-[14px] text-ink-600">None. The map shows recorded or live data only.</p>
      )}
    </section>
  )
}
