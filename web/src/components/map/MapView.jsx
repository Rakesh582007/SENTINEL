import { useCallback, useEffect } from 'react'
import { MapContainer, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import { DEFAULT_VIEW, STANDALONE } from '../../config.js'
import { useStore, useViewTick } from '../../store.js'
import Legend from '../Legend.jsx'
import AircraftLayer from './AircraftLayer.jsx'
import BaseLayers from './BaseLayers.jsx'
import CellsLayer from './CellsLayer.jsx'
import ReplayFocusBanner from './ReplayFocusBanner.jsx'

function MapBehaviour() {
  const map = useMap()
  const focus = useStore((s) => s.focus)
  const tab = useStore((s) => s.tab)

  useEffect(() => {
    if (!focus) return
    if (focus.bounds) map.flyToBounds(focus.bounds, { padding: [60, 60], maxZoom: focus.maxZoom ?? 8, duration: 0.8 })
    else if (focus.center) map.flyTo(focus.center, focus.zoom ?? Math.max(map.getZoom(), 7), { duration: 0.8 })
  }, [focus, map])

  useEffect(() => {
    const t = window.setTimeout(() => map.invalidateSize(), 30)
    return () => window.clearTimeout(t)
  }, [tab, map])

  useMapEvents({
    click: (e) => {
      const st = useStore.getState()
      if (st.tab === 'simulator' && !st.jammer.attackId && !st.picking) {
        st.setJammer({ center: [e.latlng.lat, e.latlng.lng] })
        return
      }
      if (st.picking) return
      st.clearSelection()
    },
  })
  return null
}

function MapControls() {
  const basemap = useStore((s) => s.basemap)
  const setBasemap = useStore((s) => s.setBasemap)
  const focusOn = useStore((s) => s.focusOn)
  return (
    <div className="absolute right-3 top-[86px] z-[900] flex flex-col items-end gap-2">
      <div className="flex overflow-hidden rounded-md border border-sand-400 bg-sand-50 text-[12.5px] font-semibold shadow-float" role="group" aria-label="Base map">
        {[
          ['outline', 'Chart'],
          ['tiles', 'Streets'],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={basemap === id}
            onClick={() => setBasemap(id)}
            className={`px-2.5 py-1 ${basemap === id ? 'bg-air-600 text-white' : 'text-ink-700 hover:bg-air-50'}`}
            title={id === 'outline' ? 'Offline outline map with India’s official boundary' : 'Street tiles from CARTO (needs internet; their boundaries)'}
          >
            {label}
          </button>
        ))}
      </div>
      <button
        type="button"
        onClick={() => focusOn({ center: DEFAULT_VIEW.center, zoom: DEFAULT_VIEW.zoom })}
        className="rounded-md border border-sand-400 bg-sand-50 px-2.5 py-1 text-[12.5px] font-semibold text-ink-700 shadow-float hover:bg-air-50"
      >
        North India view
      </button>
    </div>
  )
}

function FeedOverlay() {
  const tick = useViewTick()
  const connection = useStore((s) => s.connection)
  if (tick && (tick.aircraft?.length || tick.cells?.features?.length)) return null
  return (
    <div className="pointer-events-none absolute inset-0 z-[850] grid place-items-center p-4">
      <div className="pointer-events-auto max-w-md rounded-xl border border-sand-400 bg-sand-50/95 p-5 text-center shadow-float">
        {!tick ? (
          <>
            <p className="text-[18px] font-bold text-ink-900">Waiting for data…</p>
            {STANDALONE ? (
              <p className="mt-2 text-[14px] text-ink-600">Loading the recorded sample.</p>
            ) : (
              <p className="mt-2 text-[14px] leading-relaxed text-ink-600">
                {connection.state === 'reconnecting' ? 'The backend is not answering yet. ' : ''}
                Start it from the repo with <code className="rounded bg-sand-200 px-1 font-data text-[12.5px]">cd backend</code> then{' '}
                <code className="rounded bg-sand-200 px-1 font-data text-[12.5px]">uvicorn app.main:app --port 8000</code>. The map fills in within 5 seconds.
              </p>
            )}
          </>
        ) : (
          <>
            <p className="text-[18px] font-bold text-ink-900">No aircraft in the feed right now</p>
            <p className="mt-2 text-[14px] leading-relaxed text-ink-600">
              {tick.mode === 'live'
                ? STANDALONE
                  ? 'Live data comes from the real backend polling adsb.fi and adsb.lol. This standalone build only has the recorded sample: switch back to Replay.'
                  : 'Live polling is running but no aircraft have arrived yet. Check the source status, or switch back to Replay.'
                : 'The replay has no aircraft at this moment. It skips gaps on its own; give it a few seconds.'}
            </p>
          </>
        )}
      </div>
    </div>
  )
}

function StaleBanner() {
  const tick = useViewTick()
  const connection = useStore((s) => s.connection)
  if (!tick || connection.state === 'open') return null
  return (
    <div className="absolute inset-x-0 top-0 z-[860] flex justify-center p-2">
      <div className="rounded-md border border-[#E5484D] bg-[#fdecec] px-3 py-1.5 text-[13.5px] font-semibold text-[#8F1F23] shadow-float" role="alert">
        Lost the live feed. The map shows the last data received; reconnecting automatically.
      </div>
    </div>
  )
}

export default function MapView({ overlays = null, bottom = null }) {
  const placing = useStore((s) => s.tab === 'simulator' && !s.jammer.attackId)
  const picking = useStore((s) => s.picking)

  const onCellClick = useCallback((id, latlng) => {
    const st = useStore.getState()
    if (st.picking) return
    if (st.tab === 'simulator' && !st.jammer.attackId) {
      st.setJammer({ center: [latlng.lat, latlng.lng] })
      return
    }
    st.select('cell', id)
  }, [])

  const onAircraftClick = useCallback((hex) => {
    const st = useStore.getState()
    if (st.picking) {
      st.setSpoof({ target: hex })
      st.setPicking(false)
      const a = st.tick?.aircraft?.find((x) => x.hex === hex)
      st.toast(`Picked ${a?.flight || hex.toUpperCase()} as the spoofing target.`, 'ok')
    }
    st.select('aircraft', hex)
  }, [])

  return (
    <div className={`relative flex h-full w-full flex-col ${placing || picking ? 'placing' : ''}`}>
      <div className="relative h-[56vh] min-h-[300px] lg:h-auto lg:min-h-0 lg:flex-1">
        <MapContainer
          center={DEFAULT_VIEW.center}
          zoom={DEFAULT_VIEW.zoom}
          minZoom={4}
          maxZoom={10}
          zoomControl={false}
          attributionControl={false}
          worldCopyJump={false}
          maxBounds={[
            [-5, 45],
            [45, 110],
          ]}
          className="h-full w-full"
        >
          <ZoomControl position="topright" />
          <BaseLayers />
          <CellsLayer onCellClick={onCellClick} />
          {overlays}
          <AircraftLayer onAircraftClick={onAircraftClick} />
          <MapBehaviour />
        </MapContainer>
        <MapControls />
        <StaleBanner />
        <ReplayFocusBanner />
        <FeedOverlay />
      </div>
      {/* Desktop: floats over the bottom of the map. Phone: sits below it so the map stays visible. */}
      <div className="flex flex-col items-stretch gap-2 p-2 lg:pointer-events-none lg:absolute lg:inset-x-2 lg:bottom-2 lg:z-[900] lg:p-0">
        {bottom}
        <Legend />
      </div>
    </div>
  )
}
