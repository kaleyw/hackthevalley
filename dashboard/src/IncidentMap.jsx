import { Component, useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { currentCoordinates, detectionCoordinates, effectiveLocation, groupIncidents, stationName } from './mapLayout.js'

const symbols = { open: '!', acknowledged: '✓', on_scene: '◆', resolved: '✓', dismissed: '×' }
const labels = { open: 'New', acknowledged: 'Accepted', on_scene: 'On scene', resolved: 'Resolved', dismissed: 'Dismissed' }
const when = (value) => value ? new Date(value).toLocaleString() : 'Unavailable'
const coordinateText = (c) => !c ? 'Location unavailable' : `${c.lat.toFixed(5)}, ${c.lon.toFixed(5)} · ${c.precision === 'station_centroid' ? 'approximate station location' : c.precision.replaceAll('_', ' ')}`

export class MapBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <p className="map-warning">Map unavailable. Use the location briefing below; alert controls remain available.</p> : this.props.children }
}

const DOWNTOWN = [43.6510, -79.3810]
const STREET_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const STREET_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
// Lines 5 (Eglinton) and 6 (Finch West): the station data has no stops for them, so they're hidden
const HIDDEN_LINES = ['5', '6']
const isClosed = (status) => ['resolved', 'dismissed'].includes(status)

function useStreetMapSetting() {
  const [on, setOn] = useState(() => {
    try { return localStorage.getItem('streetMap') !== 'off' } catch { return true }
  })
  const toggle = () => setOn((v) => {
    try { localStorage.setItem('streetMap', v ? 'off' : 'on') } catch { /* private mode */ }
    return !v
  })
  return [on, toggle]
}

export function NetworkMap({ contexts, selectedId, onSelect, monitored = [] }) {
  const container = useRef(null)
  const map = useRef(null)
  const streets = useRef(null)
  const markers = useRef(null)
  const stationsLayer = useRef(null)
  const fitted = useRef(null)
  const [fitRequest, setFitRequest] = useState(0)
  const [networkError, setNetworkError] = useState(false)
  const [streetMap, toggleStreetMap] = useStreetMapSetting()
  const [streetsOffline, setStreetsOffline] = useState(false)

  useEffect(() => {
    const instance = L.map(container.current, { attributionControl: true }).setView(DOWNTOWN, 14)
    map.current = instance
    // Street background when online; tile errors fall back to the local TTC lines alone
    let loaded = 0
    // OpenStreetMap's tile policy needs a Referer; send just this site's origin for tiles
    // (the page itself sends none). Tiles are faded in CSS so the TTC lines stand out.
    streets.current = L.tileLayer(STREET_TILES, { maxZoom: 19, attribution: STREET_ATTRIBUTION, className: 'street-tiles', referrerPolicy: 'strict-origin' })
      .on('tileload', () => { loaded += 1; setStreetsOffline(false) })
      .on('tileerror', () => { if (loaded === 0) setStreetsOffline(true) })
    stationsLayer.current = L.layerGroup().addTo(instance)
    markers.current = L.layerGroup().addTo(instance)
    instance.attributionControl.addAttribution('TTC geography: City of Toronto')
    let cancelled = false
    Promise.all(['/maps/ttc-lines.geojson', '/maps/ttc-stations.geojson'].map((url) => fetch(url).then((r) => {
      if (!r.ok) throw new Error('Network geography unavailable')
      return r.json()
    }))).then(([lines, stations]) => {
      if (cancelled) return
      L.geoJSON(lines, {
        filter: (f) => !HIDDEN_LINES.includes(String(f.properties.ROUTE_SHORT_NAME)),
        // Line 1 (the yellow U) keeps its TTC colour; the other lines stay charcoal
        style: (f) => (String(f.properties.ROUTE_SHORT_NAME) === '1'
          ? { color: '#FFC524', weight: 6, opacity: 1 }
          : { color: '#1a1a1a', weight: 4, opacity: 0.55 }),
        onEachFeature: (f, layer) => { if (f.properties.ROUTE_SHORT_NAME) layer.bindTooltip(`Line ${f.properties.ROUTE_SHORT_NAME}`, { sticky: true }) },
      }).addTo(instance)
      L.geoJSON(stations, {
        pointToLayer: (_, latlng) => L.circleMarker(latlng, { radius: 3.5, color: '#1a1a1a', fillColor: '#fafafa', fillOpacity: 1, weight: 1.5 }),
        onEachFeature: (f, layer) => {
          const label = document.createElement('span')
          label.textContent = stationName(f.properties.PT_NAME)
          layer.bindTooltip(label)
        },
      }).addTo(instance)
      stationsLayer.current.bringToFront?.()
      markers.current.bringToFront?.()
    }).catch(() => { if (!cancelled) setNetworkError(true) })
    const resize = new ResizeObserver(() => instance.invalidateSize())
    resize.observe(container.current)
    return () => { cancelled = true; resize.disconnect(); instance.remove(); map.current = null }
  }, [])

  useEffect(() => {
    if (!map.current || !streets.current) return
    if (streetMap) streets.current.addTo(map.current)
    else streets.current.remove()
  }, [streetMap])

  // Stations we have cameras at: a small blue pin with a permanent name label
  useEffect(() => {
    if (!map.current) return
    stationsLayer.current.clearLayers()
    for (const station of monitored) {
      const { lat, lon } = station.coordinates
      L.circleMarker([lat, lon], { radius: 8, color: '#fafafa', weight: 3, fillColor: '#1a1a1a', fillOpacity: 1 })
        .bindTooltip(stationName(station.station_name), { permanent: true, direction: 'right', offset: [10, 0], className: 'station-label' })
        .addTo(stationsLayer.current)
    }
  }, [monitored])

  useEffect(() => {
    if (!map.current) return
    markers.current.clearLayers()
    const groups = groupIncidents(contexts)
    let tallest = 0
    for (const group of groups) {
      const stack = document.createElement('div')
      stack.className = 'incident-stack'
      const heading = document.createElement('div')
      heading.className = 'incident-stack-heading'
      const place = group.station ?? 'This location'
      heading.textContent = group.contexts.length > 1 ? `${place} · ${group.contexts.length} alerts` : place
      stack.appendChild(heading)
      for (const context of group.contexts) {
        const event = context.incident
        const escalated = event.escalation_level > 0 && !isClosed(event.status)
        const text = `${escalated ? '⚠ Escalated' : `${symbols[event.status]} ${labels[event.status]}`} #${event.id}`
        const element = document.createElement('button')
        element.type = 'button'
        element.className = `incident-pin incident-pin--${escalated ? 'escalated' : event.status} ${event.id === selectedId ? 'incident-pin-selected' : ''}`
        element.textContent = text
        element.setAttribute('aria-label', `Incident #${event.id} at ${place}: ${escalated ? 'Escalated' : labels[event.status]}`)
        element.setAttribute('aria-pressed', String(event.id === selectedId))
        L.DomEvent.on(element, 'click', (e) => { L.DomEvent.stop(e); onSelect?.(event.id) })
        stack.appendChild(element)
      }
      const stackHeight = Math.min(180, group.contexts.length * 32 + 40)
      tallest = Math.max(tallest, stackHeight)
      L.DomEvent.disableScrollPropagation(stack)
      L.DomEvent.disableClickPropagation(stack)
      const { lat, lon } = group.coordinates
      const active = group.contexts.some((c) => !isClosed(c.incident.status))
      // A pin exactly at the station, and the alert box floating above it so the station stays visible
      L.circleMarker([lat, lon], { radius: 9, color: '#fafafa', weight: 3, fillColor: active ? '#da251d' : '#1a1a1a', fillOpacity: active ? 1 : 0.4, className: active ? 'alert-pin-pulse' : '' })
        .addTo(markers.current)
      L.marker([lat, lon], {
        icon: L.divIcon({ html: stack, className: 'incident-pin-shell incident-callout', iconSize: [172, stackHeight], iconAnchor: [86, stackHeight + 18] }),
        keyboard: false,
        zIndexOffset: active ? 1000 : 0,
      }).addTo(markers.current)
    }
    const points = groups.map((g) => [g.coordinates.lat, g.coordinates.lon])
    const fitKey = `${fitRequest}:${monitored.length}:${contexts.map((c) => {
      const p = currentCoordinates(c)
      return `${c.incident.id}:${p?.lat}:${p?.lon}`
    }).sort().join('|')}`
    if (fitted.current !== fitKey) {
      if (points.length) {
        // Leave room above the pins for the alert boxes
        map.current.fitBounds(L.latLngBounds(points), { paddingTopLeft: [40, tallest + 50], paddingBottomRight: [40, 40], maxZoom: 15, animate: false })
      } else if (monitored.length) {
        map.current.setView([monitored[0].coordinates.lat, monitored[0].coordinates.lon], 14, { animate: false })
      }
      fitted.current = fitKey
    }
  }, [contexts, selectedId, onSelect, fitRequest, monitored])

  const mappedCount = groupIncidents(contexts).reduce((count, group) => count + group.contexts.length, 0)
  return <div><div className="map-overview-heading"><p className="map-caption">{mappedCount ? `Showing ${mappedCount} active alert${mappedCount > 1 ? 's' : ''}` : 'No active alerts'}{contexts.length > mappedCount ? ` · ${contexts.length - mappedCount} location unavailable` : ''}</p><div className="map-actions"><label className="map-check"><input type="checkbox" checked={streetMap} onChange={toggleStreetMap} /> Street map</label><button type="button" onClick={() => setFitRequest((value) => value + 1)}>Re-centre</button></div></div>
    <div ref={container} className="network-map" aria-label="TTC incident location map" />
    {networkError && <p className="map-warning">Geographic layer unavailable. Location briefing remains available.</p>}
    {streetMap && streetsOffline && <p className="map-caption">Street map unavailable (no internet); showing TTC lines only.</p>}
    <p className="map-caption"><span className="legend-dot legend-camera" /> Camera station · <span className="legend-dot legend-alert" /> Alert · ! New · ✓ Accepted · ◆ On scene · ⚠ Escalated</p>
    <p className="map-caption"><a href="/maps/SOURCES.md" target="_blank" rel="noreferrer">Map data sources</a></p>
  </div>
}

export function LocationDetails({ context, connected = true }) {
  if (!context) return <p className="map-caption">Loading location…</p>
  const location = effectiveLocation(context)
  return <div className="location-details">
    <p><strong>Incident #{context.incident.id}</strong> · {labels[context.incident.status]}{context.incident.escalation_level > 0 ? ' · ⚠ Escalated' : ''}</p>
    <p>Person may need help · {when(context.incident.detected_at)}</p>
    <p className={connected ? 'map-online' : 'map-warning'}>{connected ? 'Location updates connected' : 'Disconnected — retaining last known location'}</p>
    <dl>
      <dt>Station / platform</dt><dd>{stationName(location?.station_name) ?? 'Location unavailable'}{location?.platform_label ? ` · ${location.platform_label}` : ''}</dd>
      <dt>Line / direction</dt><dd>{[location?.line, location?.direction].filter(Boolean).join(' · ') || 'Unavailable'}</dd>
      <dt>Location</dt><dd>{coordinateText(location?.coordinates ?? detectionCoordinates(context))}</dd>
    </dl>
    <p className="map-caption">Last updated {when(context.last_updated_at)}</p>
  </div>
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true } catch { return false }
}

export default function IncidentMapPanel({ events, selectedId, onSelect, connected }) {
  const [contexts, setContexts] = useState([])
  const [online, setOnline] = useState(false)
  const [error, setError] = useState('')
  const [operatorKey, setOperatorKey] = useState(() => sessionStorage.getItem('mapOperatorKey') || '')
  const [link, setLink] = useState(null)
  const [notice, setNotice] = useState('')
  const [stations, setStations] = useState([])
  const [stationId, setStationId] = useState('')
  const [platform, setPlatform] = useState('')
  const [direction, setDirection] = useState('')
  const [line, setLine] = useState('')
  const [meeting, setMeeting] = useState('')
  const [verified, setVerified] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const ids = events.map((e) => e.id).join(',')
  const [monitored, setMonitored] = useState([])
  // Only active alerts on the map, plus one picked from the history list
  const mapContexts = contexts.filter((c) => !isClosed(c.incident.status) || c.incident.id === selectedId)
  const selected = contexts.find((c) => c.incident.id === selectedId)
  const event = events.find((e) => e.id === selectedId)
  const loadRef = useRef(null)

  useEffect(() => {
    let closed = false
    const load = async () => {
      const idsToLoad = ids.split(',').filter(Boolean)
      const results = await Promise.allSettled(idsToLoad.map((id) => fetch(`/api/maps/events/${id}`).then(async (r) => {
        if (!r.ok) throw new Error('Location service unavailable')
        return await r.json()
      })))
      if (closed) return
      const fresh = results.filter((r) => r.status === 'fulfilled').map((r) => r.value)
      setContexts((prev) => idsToLoad.map((id) => fresh.find((c) => c.incident.id === Number(id)) ?? prev.find((c) => c.incident.id === Number(id))).filter(Boolean))
      setOnline(results.every((r) => r.status === 'fulfilled'))
    }
    loadRef.current = load
    load()
    const timer = setInterval(load, 2000)
    return () => { closed = true; clearInterval(timer) }
  }, [ids])

  useEffect(() => { fetch('/maps/ttc-stations.geojson').then((r) => r.json()).then((d) => setStations(d.features)).catch(() => {}) }, [])
  useEffect(() => {
    const load = () => fetch('/api/maps/monitored').then((r) => r.json()).then(setMonitored).catch(() => {})
    load()
    const timer = setInterval(load, 15000)
    return () => clearInterval(timer)
  }, [])
  const choose = (id) => { setLink(null); setNotice(''); setError(''); onSelect(id) }

  const command = async (path, method, body) => {
    setError('')
    try {
      const response = await fetch(`/api${path}`, { method, headers: { 'Content-Type': 'application/json', 'X-Map-Operator-Key': operatorKey }, body: body === undefined ? undefined : JSON.stringify(body) })
      const value = await response.json()
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : 'Invalid location metadata')
      loadRef.current?.()
      return value
    } catch (e) { setError(e.message); return null }
  }
  const location = () => {
    const station = stations.find((s) => String(s.properties.PT_ID) === stationId)
    return { kind: 'platform', station_id: stationId || null, station_name: station?.properties.PT_NAME ?? null, platform_label: platform || null, direction: direction || null, line: line || null, source: 'configured', meeting_point: meeting && verified ? { label: meeting, verified: true } : null }
  }
  const prepareLink = async (renew = false) => {
    const result = await command(`/maps/events/${selectedId}/link`, 'POST', { renew })
    if (result) setLink(result.url)
  }

  return <div className="map-view">
    <section className="map-main" aria-label="Incident map">
      <div className="map-panel-heading"><div><p className="section-label">TTC LOCATION</p><h2 className="map-title">Incident map</h2></div><span className={online && connected ? 'map-online' : 'map-warning'}>{online && connected ? '● Connected' : '○ Reconnecting'}</span></div>
      <MapBoundary><NetworkMap contexts={mapContexts} selectedId={selectedId} onSelect={choose} monitored={monitored} /></MapBoundary>
    </section>
    <aside className="map-side" aria-label="Alert location details">
      <label className="field"><span>Alert details</span><select aria-label="Selected map incident" value={selectedId ?? ''} onChange={(e) => choose(Number(e.target.value))}><option value="" disabled>{events.length ? 'Select an alert' : 'No alerts yet'}</option>{events.map((e) => <option key={e.id} value={e.id}>#{e.id} · {e.location} · {labels[e.status]}{e.escalation_level > 0 ? ' · Escalated' : ''}</option>)}</select></label>
      <LocationDetails context={selected} connected={online && connected} />
      {selected && <>
        <div className="map-actions"><button onClick={async () => setNotice(await copyText(selected.briefing) ? 'Location briefing copied' : 'Copy the briefing from the text box below')}>Copy location briefing</button></div>
        <textarea aria-label="Text location briefing" readOnly value={selected.briefing} rows={4} />
        <div className="map-notice"><strong>Share with a responder</strong><br />A read-only link to this alert's location. It doesn't call or message anyone; send it yourself.<br />Link: {selected.handoff?.state ?? 'unavailable'}</div>
        <label className="field"><span>Map operator key</span><input type="password" autoComplete="off" value={operatorKey} onChange={(e) => { setOperatorKey(e.target.value); sessionStorage.setItem('mapOperatorKey', e.target.value) }} placeholder="MAP_OPERATOR_KEY from your .env" /></label>
        <div className="map-actions"><button onClick={() => prepareLink()}>Prepare / reuse map link</button><button onClick={() => prepareLink(true)}>Renew link</button><button onClick={async () => { if (await command(`/maps/events/${selectedId}/link`, 'DELETE')) { setLink(null); setNotice('Link revoked') } }}>Revoke link</button></div>
        {selected.handoff?.expires_at && <p className="map-caption">Link expires {when(selected.handoff.expires_at)}. Renewing invalidates the previous link.</p>}
        {link && <><input aria-label="Restricted responder link" readOnly value={link} /><div className="map-actions"><button onClick={async () => setNotice(await copyText(link) ? 'Map link copied' : 'Select and copy the link above')}>Copy map link</button><a href={link} target="_blank" rel="noreferrer">Open responder view ↗</a></div></>}
      </>}
      <button className="map-config-toggle" onClick={() => setShowConfig(!showConfig)}>{showConfig ? 'Hide' : 'Change'} camera location</button>
      {showConfig && event && <div className="map-config">
        <p className="map-caption">Set the station for camera {event.camera_id} (future alerts) and this alert. Cameras default to Union Station.</p>
        <label className="field"><span>Station</span><select value={stationId} onChange={(e) => setStationId(e.target.value)}><option value="">Location unavailable</option>{stations.map((s) => <option key={s.properties.PT_ID} value={s.properties.PT_ID}>{stationName(s.properties.PT_NAME)}</option>)}</select></label>
        <label className="field"><span>Platform label</span><input value={platform} onChange={(e) => setPlatform(e.target.value)} placeholder="Optional; staff-provided" /></label>
        <label className="field"><span>Direction</span><input value={direction} onChange={(e) => setDirection(e.target.value)} placeholder="Optional" /></label>
        <label className="field"><span>Line</span><input value={line} onChange={(e) => setLine(e.target.value)} placeholder="Optional" /></label>
        <label className="field"><span>Meeting point description</span><input value={meeting} onChange={(e) => setMeeting(e.target.value)} placeholder="Only enter a verified meeting point" /></label>
        <label className="map-check"><input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} /> Staff verified this meeting point</label>
        <div className="map-actions"><button disabled={Boolean(meeting) && !verified} onClick={async () => {
          const metadata = location()
          const saved = await command(`/maps/cameras/${encodeURIComponent(event.camera_id)}`, 'PUT', metadata)
          if (saved && await command(`/maps/events/${selectedId}/location`, 'PUT', saved)) setNotice('Camera location saved')
        }}>Save location</button></div>
        <p className="map-caption">Station points are approximate. No platform or entrance coordinates are invented.</p>
      </div>}
      {notice && <p role="status" className="map-notice">{notice}</p>}{error && <p role="alert" className="map-warning">{error}</p>}
    </aside>
  </div>
}
