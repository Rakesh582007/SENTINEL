import L from 'leaflet'
import { memo, useMemo, useState } from 'react'
import { Marker, Popup, useMap, useMapEvents } from 'react-leaflet'
import { BAD_REASON, SPOOF_REASON, hasSpoofEvidence } from '../../lib/states.js'
import { useDerived, useStore, useViewTick } from '../../store.js'
import { Fact, InjectedBadge } from '../ui.jsx'

const PLANE =
  'M12 1.6c.8 0 1.4 1 1.4 2.3v5.3l8.1 4.6v2l-8.1-2.4v4.7l2.4 1.8v1.6L12 20.5l-3.8 1v-1.6l2.4-1.8v-4.7L2.5 15.8v-2l8.1-4.6V3.9c0-1.3.6-2.3 1.4-2.3z'

export function variantOf(a) {
  if (a.on_ground) return 'ground'
  if (a.pos_lost) return 'lost'
  if (hasSpoofEvidence(a.spoof)) return 'spoof'
  if (a.bad) return 'bad'
  return 'ok'
}

const iconCache = new Map()
function aircraftIcon(variant, track, injected, selected, tagText, small) {
  const rot = Math.round((track ?? 0) / 5) * 5
  const key = `${variant}|${rot}|${injected ? 1 : 0}|${selected ? 1 : 0}|${tagText ? 1 : 0}|${small ? 1 : 0}`
  if (iconCache.has(key)) return iconCache.get(key)
  const hollow = variant === 'lost'
  const fill = variant === 'ground' ? '#7D8CA1' : hollow ? '#FBF8F1' : '#2C4467'
  const ring =
    variant === 'bad'
      ? '<circle cx="12" cy="12" r="11" fill="none" stroke="#E8A33C" stroke-width="2.4"/>'
      : variant === 'spoof'
        ? '<circle cx="12" cy="12" r="11" fill="none" stroke="#9B5DE5" stroke-width="2.4"/>'
        : variant === 'lost'
          ? '<circle cx="12" cy="12" r="11" fill="none" stroke="#E8A33C" stroke-width="1.8" stroke-dasharray="3 2.4"/>'
          : ''
  const sel = selected ? '<circle cx="12" cy="12" r="11.6" fill="rgba(30,90,168,0.12)" stroke="#1E5AA8" stroke-width="2.4"/>' : ''
  const scale = variant === 'ground' ? 0.72 : 0.86
  const quiet = variant === 'ok' || variant === 'ground'
  const html = `<div class="ac-icon${small ? ' small' : ''}${quiet && !selected && !injected ? ' quiet' : ''}"><svg viewBox="-1 -1 26 26" aria-hidden="true">${sel}${ring}<g transform="rotate(${rot} 12 12) translate(12 12) scale(${scale}) translate(-12 -12)"><path d="${PLANE}" fill="${fill}" stroke="${
    hollow ? '#2C4467' : '#FBF8F1'
  }" stroke-width="${hollow ? 1.5 : 1.1}" stroke-linejoin="round" paint-order="stroke"/></g></svg>${
    injected && tagText ? '<span class="inj-tag">INJECTED</span>' : ''
  }</div>`
  const icon = L.divIcon({ className: 'leaflet-div-icon bare', iconSize: [0, 0], html })
  iconCache.set(key, icon)
  return icon
}

const AircraftMarker = memo(function AircraftMarker({ a, selected, onPick, tagText, small }) {
  const variant = variantOf(a)
  const handlers = useMemo(
    () => ({
      click: (e) => {
        L.DomEvent.stopPropagation(e)
        onPick(a.hex)
      },
    }),
    [a.hex, onPick],
  )
  const z = selected ? 1000 : a.injected || variant === 'bad' || variant === 'spoof' ? 400 : 0
  return (
    <Marker
      position={[a.lat, a.lon]}
      icon={aircraftIcon(variant, a.track, Boolean(a.injected), selected, tagText, small)}
      eventHandlers={handlers}
      zIndexOffset={z}
      title={`${a.flight || a.hex.toUpperCase()}`}
      alt={`Aircraft ${a.flight || a.hex}`}
    />
  )
})

function gpsSentence(a) {
  if (a.pos_lost) return 'Position lost: showing the last known position'
  if (a.bad) return BAD_REASON[a.bad] || a.bad
  return 'Healthy'
}

export function AircraftDetails({ a }) {
  const tick = useViewTick()
  const spoofCodes = (a.spoof || []).filter(Boolean)
  return (
    <div className="w-[250px]">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-data text-[16px] font-bold text-ink-900">{a.flight || 'No callsign'}</span>
        <span className="font-data text-[12px] text-ink-600">{a.hex.toUpperCase()}</span>
      </div>
      {a.injected ? (
        <div className="mt-1.5">
          <InjectedBadge />
          <span className="ml-1.5 font-data text-[11px] text-ink-600">{a.injected}</span>
        </div>
      ) : null}
      <dl className="mt-2">
        <Fact label="GPS">{gpsSentence(a)}</Fact>
        {spoofCodes.length ? <Fact label="Spoofing check">{spoofCodes.map((c) => SPOOF_REASON[c] || c).join(', ')}</Fact> : null}
        <Fact label="Altitude" mono>
          {a.on_ground ? 'on ground' : a.alt_baro != null ? `${a.alt_baro.toLocaleString('en-IN')} ft` : '–'}
        </Fact>
        <Fact label="GPS altitude" mono>
          {a.alt_geom != null ? `${a.alt_geom.toLocaleString('en-IN')} ft` : '–'}
        </Fact>
        <Fact label="Speed, track" mono>
          {a.gs != null ? `${Math.round(a.gs)} kt` : '–'}, {a.track != null ? `${Math.round(a.track)}°` : '–'}
        </Fact>
        <Fact label="NIC / NACp" mono>
          {a.nic ?? '–'} / {a.nac_p ?? '–'}
        </Fact>
        <Fact label="Source" mono>
          {a.source}, {a.age_s != null ? `${Math.round(a.age_s)} s old` : '–'}
        </Fact>
      </dl>
      {tick?.mode === 'replay' ? <p className="mt-2 text-[12px] text-ink-600">Recorded data, replayed.</p> : null}
    </div>
  )
}

export default function AircraftLayer({ onAircraftClick }) {
  const d = useDerived()
  const map = useMap()
  const [zoom, setZoom] = useState(map.getZoom())
  useMapEvents({ zoomend: () => setZoom(map.getZoom()) })
  const tagText = zoom >= 7
  const selection = useStore((s) => s.selection)
  const clearSelection = useStore((s) => s.clearSelection)
  const selectedHex = selection?.kind === 'aircraft' ? selection.id : null
  const selected = selectedHex ? d.aircraftByHex.get(selectedHex) : null

  const popupHandlers = useMemo(
    () => ({
      remove: () => {
        const sel = useStore.getState().selection
        if (sel?.kind === 'aircraft' && sel.id === selectedHex) clearSelection()
      },
    }),
    [selectedHex, clearSelection],
  )

  return (
    <>
      {d.aircraft.map((a) =>
        a.lat != null && a.lon != null ? <AircraftMarker key={a.hex} a={a} selected={a.hex === selectedHex} onPick={onAircraftClick} tagText={tagText || a.hex === selectedHex || String(a.injected || '').includes('spoof')} small={zoom <= 6} /> : null,
      )}
      {selected ? (
        <Popup key={selectedHex} position={[selected.lat, selected.lon]} offset={[0, -8]} autoPan={false} eventHandlers={popupHandlers}>
          <AircraftDetails a={selected} />
        </Popup>
      ) : null}
    </>
  )
}
