import { Component, useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import './map.css'
import { currentCoordinates, detectionCoordinates, effectiveLocation, groupIncidents, uniqueTrains } from './mapLayout.js'

const symbols = { open: '!', acknowledged: '✓', on_scene: '◆', resolved: '✓', dismissed: '×' }
const labels = { open: 'New', acknowledged: 'Accepted', on_scene: 'On scene', resolved: 'Resolved', dismissed: 'Dismissed' }
const colors = { open: '#dc2626', acknowledged: '#b45309', on_scene: '#2563eb', resolved: '#15803d', dismissed: '#64748b' }
export const when = (value) => value ? new Date(value).toLocaleString() : 'Unavailable'
const coordinateText = (c) => !c ? 'Location unavailable' : `${c.lat.toFixed(5)}, ${c.lon.toFixed(5)} · ${c.precision === 'station_centroid' ? 'approximate station location' : c.precision.replaceAll('_', ' ')}`

export class MapBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <p className="map-warning">Map unavailable. Use the location briefing below; alert controls remain available.</p> : this.props.children }
}

export function NetworkMap({ contexts, selectedId, onSelect, disconnected = false }) {
  const container = useRef(null)
  const map = useRef(null)
  const markers = useRef(null)
  const trainLayer = useRef(null)
  const fitted = useRef(null)
  const [fitRequest, setFitRequest] = useState(0)
  const [networkError, setNetworkError] = useState(false)

  useEffect(() => {
    const instance = L.map(container.current, { attributionControl: true }).setView([43.69, -79.40], 11)
    map.current = instance
    markers.current = L.layerGroup().addTo(instance)
    trainLayer.current = L.layerGroup().addTo(instance)
    instance.attributionControl.addAttribution('Local TTC geography · see data sources below')
    let cancelled = false
    Promise.all(['/maps/ttc-lines.geojson', '/maps/ttc-stations.geojson'].map((url) => fetch(url).then((r) => {
      if (!r.ok) throw new Error('Network geography unavailable')
      return r.json()
    }))).then(([lines, stations]) => {
      if (cancelled) return
      L.geoJSON(lines, { style: (f) => ({ color: f.properties.ROUTE_COLOR ? `#${f.properties.ROUTE_COLOR.replace('#', '')}` : '#64748b', weight: 4 }) }).addTo(instance)
      L.geoJSON(stations, {
        pointToLayer: (_, latlng) => L.circleMarker(latlng, { radius: 3, color: '#334155', fillColor: 'white', fillOpacity: 1, weight: 1 }),
        onEachFeature: (f, layer) => {
          const label = document.createElement('span')
          label.textContent = f.properties.PT_NAME
          layer.bindTooltip(label)
        },
      }).addTo(instance)
    }).catch(() => { if (!cancelled) setNetworkError(true) })
    const resize = new ResizeObserver(() => instance.invalidateSize())
    resize.observe(container.current)
    return () => { cancelled = true; resize.disconnect(); instance.remove(); map.current = null }
  }, [])

  useEffect(() => {
    if (!map.current) return
    markers.current.clearLayers()
    const groups = groupIncidents(contexts)
    for (const group of groups) {
      const stack = document.createElement('div')
      stack.className = 'incident-stack'
      if (group.contexts.length > 1) {
        const heading = document.createElement('div')
        heading.className = 'incident-stack-heading'
        heading.textContent = `${group.contexts.length} alerts at this location`
        stack.appendChild(heading)
      }
      for (const context of group.contexts) {
        const event = context.incident
        const escalated = event.escalation_level > 0 && !['resolved', 'dismissed'].includes(event.status)
        const text = `${escalated ? '⚠ Escalated' : `${symbols[event.status]} ${labels[event.status]}`} #${event.id}`
        const element = document.createElement('button')
        element.type = 'button'
        element.className = `incident-pin ${event.id === selectedId ? 'incident-pin-selected' : ''}`
        element.style.backgroundColor = escalated ? '#7e22ce' : colors[event.status]
        element.textContent = text
        element.setAttribute('aria-label', `Incident #${event.id}: ${escalated ? 'Escalated' : labels[event.status]}`)
        element.setAttribute('aria-pressed', String(event.id === selectedId))
        L.DomEvent.on(element, 'click', (e) => { L.DomEvent.stop(e); onSelect?.(event.id) })
        stack.appendChild(element)
        // The immutable snapshot remains visible when a train or transfer moves.
        const original = detectionCoordinates(context)
        if (event.id === selectedId && original) {
          L.circleMarker([original.lat, original.lon], { radius: 10, color: '#0f172a', fillOpacity: 0, dashArray: '4 3' })
            .bindTooltip('Detection-location snapshot (unchanged)').addTo(markers.current)
        }
      }
      const stackHeight = Math.min(180, group.contexts.length * 32 + (group.contexts.length > 1 ? 28 : 0) + 12)
      L.DomEvent.disableScrollPropagation(stack)
      L.DomEvent.disableClickPropagation(stack)
      L.marker([group.coordinates.lat, group.coordinates.lon], {
        icon: L.divIcon({ html: stack, className: 'incident-pin-shell', iconSize: [172, stackHeight], iconAnchor: [86, stackHeight / 2] }),
        keyboard: false,
        zIndexOffset: group.contexts.some((c) => !['resolved', 'dismissed'].includes(c.incident.status)) ? 1000 : 0,
      }).addTo(markers.current)
    }
    const points = groups.map((g) => [g.coordinates.lat, g.coordinates.lon])
    for (const context of uniqueTrains(contexts)) points.push([context.latest_train.latest.lat, context.latest_train.latest.lon])
    const fitKey = `${fitRequest}:${contexts.map((c) => {
      const p = currentCoordinates(c)
      return `${c.incident.id}:${p?.lat}:${p?.lon}`
    }).sort().join('|')}`
    if (points.length && fitted.current !== fitKey) {
      map.current.fitBounds(L.latLngBounds(points), { padding: [105, 100], maxZoom: 14, animate: false })
      fitted.current = fitKey
    }
  }, [contexts, selectedId, onSelect, fitRequest])

  useEffect(() => {
    if (!map.current) return
    trainLayer.current.clearLayers()
    let animation
    const trains = uniqueTrains(contexts)
    const moving = trains.map((context) => {
      const train = context.latest_train
      const latest = train.latest
      const element = document.createElement('span')
      element.className = 'train-pin'
      element.textContent = `▣ ${latest.train_id} · ${latest.source}`
      const marker = L.marker([latest.lat, latest.lon], { icon: L.divIcon({ html: element, className: 'incident-pin-shell', iconSize: [180, 30] }), title: 'Train position, not verified person location' }).addTo(trainLayer.current)
      return { train, marker, serverNow: Date.parse(context.server_time ?? new Date().toISOString()) }
    })
    const started = performance.now()
    const draw = () => {
      const elapsed = performance.now() - started
      let keepAnimating = false
      for (const { train, marker, serverNow } of moving) {
        const observedNow = serverNow + elapsed
        const latestTime = Date.parse(train.latest.observed_at)
        const previousTime = Date.parse(train.previous?.observed_at)
        const gap = latestTime - previousTime
        const fresh = !disconnected && train.connected && !train.stale && observedNow - latestTime <= train.fresh_for_seconds * 1000
        // Delayed interpolation between two known fresh samples; never extrapolate.
        if (fresh && train.previous && gap > 0 && gap <= train.fresh_for_seconds * 1000) {
          const ratio = Math.max(0, Math.min(1, (observedNow - latestTime) / gap))
          marker.setLatLng([train.previous.lat + ratio * (train.latest.lat - train.previous.lat), train.previous.lon + ratio * (train.latest.lon - train.previous.lon)])
          keepAnimating ||= ratio < 1
        }
      }
      if (keepAnimating) animation = requestAnimationFrame(draw)
    }
    draw()
    return () => cancelAnimationFrame(animation)
  }, [contexts, disconnected])

  const mappedCount = groupIncidents(contexts).reduce((count, group) => count + group.contexts.length, 0)
  return <div><div className="map-overview-heading"><p className="map-caption">Showing all {mappedCount} located alerts{contexts.length > mappedCount ? ` · ${contexts.length - mappedCount} location unavailable` : ''}. Select a label for details.</p><button type="button" onClick={() => setFitRequest((value) => value + 1)}>Fit all alerts</button></div>
    <div ref={container} className="network-map" aria-label="TTC incident location map" />
    {networkError && <p className="map-warning">Geographic layer unavailable. Location briefing remains available.</p>}
    <p className="map-caption">! New · ✓ Accepted · ⚠ Escalated · ✓ Resolved · ▣ Train (not verified person location)</p>
    <p className="map-caption">Offline vector map; no external map tiles. <a href="/maps/SOURCES.md" target="_blank" rel="noreferrer">Geographic sources and limitations</a></p>
  </div>
}

export function LocationDetails({ context, connected = true }) {
  const [clock, setClock] = useState(Date.now())
  useEffect(() => { const id = setInterval(() => setClock(Date.now()), 1000); return () => clearInterval(id) }, [])
  if (!context) return <p className="map-caption">Loading location…</p>
  const location = effectiveLocation(context)
  const train = context.latest_train
  const age = train ? Math.max(0, train.age_seconds + (clock - (context.receivedAt ?? clock)) / 1000) : null
  const stale = train && (train.stale || age > train.fresh_for_seconds)
  return <div className="location-details">
    <p><strong>Incident #{context.incident.id}</strong> · {labels[context.incident.status]}{context.incident.escalation_level > 0 ? ' · ⚠ Escalated' : ''}</p>
    <p>Possible fall detected · {when(context.incident.detected_at)}</p>
    <p className={connected ? 'map-online' : 'map-warning'}>{connected ? 'Location updates connected' : 'Disconnected — retaining last known location'}</p>
    <dl>
      <dt>Station / platform</dt><dd>{location?.station_name ?? 'Location unavailable'}{location?.platform_label ? ` · ${location.platform_label}` : ''}</dd>
      <dt>Line / direction</dt><dd>{[location?.line, location?.direction].filter(Boolean).join(' · ') || 'Unavailable'}</dd>
      <dt>Train / car</dt><dd>{[location?.train_id, location?.car_id].filter(Boolean).join(' / ') || 'Not configured'}</dd>
      <dt>Detection snapshot</dt><dd>{coordinateText(detectionCoordinates(context))}<br />Captured {when(context.snapshot?.captured_at)}{context.snapshot?.train_position && ` · ${context.snapshot.train_position.source}`}</dd>
      <dt>Current location context</dt><dd>{coordinateText(location?.coordinates)} · {location?.source ?? 'unavailable'}</dd>
      <dt>Verified meeting point</dt><dd>{location?.meeting_point?.label ?? 'Not configured'}{location?.meeting_point?.coordinates && ` · ${coordinateText(location.meeting_point.coordinates)}`}</dd>
    </dl>
    {context.transfer && <p className="map-notice">Staff-confirmed transfer to platform · {when(context.transfer.confirmed_at)}. Detection snapshot preserved.</p>}
    {train ? <div className={stale || !train.connected ? 'map-warning' : 'map-notice'}><strong>▣ Latest train position · {train.latest.source} · {stale ? 'STALE' : 'fresh'} · {train.connected ? 'provider connected' : 'provider disconnected'}</strong><br />{coordinateText({ ...train.latest, precision: 'approximate' })}<br />Observed {when(train.latest.observed_at)} · {Math.floor(age)}s old<br />Train position is not a verified person location.</div> : location?.kind === 'train' && <p className="map-warning">Train location unavailable. No movement inferred.</p>}
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
  const [kind, setKind] = useState('platform')
  const [platform, setPlatform] = useState('')
  const [direction, setDirection] = useState('northbound')
  const [line, setLine] = useState('')
  const [car, setCar] = useState('demo-car-1')
  const [meeting, setMeeting] = useState('')
  const [verified, setVerified] = useState(false)
  const [simMode, setSimMode] = useState('unknown')
  const [showConfig, setShowConfig] = useState(false)
  const ids = events.map((e) => e.id).join(',')
  const selected = contexts.find((c) => c.incident.id === selectedId)
  const event = events.find((e) => e.id === selectedId)
  const loadRef = useRef(null)

  useEffect(() => {
    let closed = false
    const load = async () => {
      const idsToLoad = ids.split(',').filter(Boolean)
      const results = await Promise.allSettled(idsToLoad.map((id) => fetch(`/api/maps/events/${id}`).then(async (r) => {
        if (!r.ok) throw new Error('Location service unavailable')
        return { ...await r.json(), receivedAt: Date.now() }
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

  useEffect(() => { setLink(null); setNotice(''); setError('') }, [selectedId])
  useEffect(() => { fetch('/maps/ttc-stations.geojson').then((r) => r.json()).then((d) => setStations(d.features)).catch(() => {}) }, [])

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
    return { kind, station_id: stationId || null, station_name: station?.properties.PT_NAME ?? null, platform_label: platform || null, direction, line: kind === 'train' ? '1' : line || null, source: kind === 'train' ? 'simulated' : 'configured', train_id: kind === 'train' ? 'DEMO-T1' : null, car_id: kind === 'train' ? car : null, meeting_point: meeting && verified ? { label: meeting, verified: true } : null }
  }
  const prepareLink = async (renew = false) => {
    const result = await command(`/maps/events/${selectedId}/link`, 'POST', { renew })
    if (result) setLink(result.url)
  }

  return <aside className="incident-map-panel" aria-label="Incident map panel">
    <div className="map-panel-heading"><div><p className="map-eyebrow">TTC LOCATION CONTEXT</p><h2>Incident map</h2></div><span className={online && connected ? 'map-online' : 'map-warning'}>{online && connected ? '● Connected' : '○ Reconnecting'}</span></div>
    <label>Incident details — all located alerts stay on the map<select aria-label="Selected map incident" value={selectedId ?? ''} onChange={(e) => onSelect(Number(e.target.value))}>{events.map((e) => <option key={e.id} value={e.id}>#{e.id} · {e.location} · {labels[e.status]}{e.escalation_level > 0 ? ' · Escalated' : ''}</option>)}</select></label>
    <MapBoundary><NetworkMap contexts={contexts} selectedId={selectedId} onSelect={onSelect} disconnected={!online || !connected} /></MapBoundary>
    <LocationDetails context={selected} connected={online && connected} />
    {selected && <>
      <div className="map-actions"><button onClick={async () => setNotice(await copyText(selected.briefing) ? 'Location briefing copied' : 'Copy the briefing from the text box below')}>Copy location briefing</button></div>
      <textarea aria-label="Text location briefing" readOnly value={selected.briefing} rows={4} />
      <div className="map-notice"><strong>Demo handoff only</strong><br />No calls, SMS, email, or emergency-service map delivery are configured.<br />Link: {selected.handoff?.state ?? 'unavailable'} · Delivery: unsupported · Responder acknowledgment: none</div>
      <label>Map operator key <input type="password" autoComplete="off" value={operatorKey} onChange={(e) => { setOperatorKey(e.target.value); sessionStorage.setItem('mapOperatorKey', e.target.value) }} placeholder="MAP_OPERATOR_KEY from your .env" /></label>
      <div className="map-actions"><button onClick={() => prepareLink()}>Prepare / reuse map link</button><button onClick={() => prepareLink(true)}>Renew link</button><button onClick={async () => { if (await command(`/maps/events/${selectedId}/link`, 'DELETE')) { setLink(null); setNotice('Link revoked') } }}>Revoke link</button></div>
      {selected.handoff?.expires_at && <p className="map-caption">Link expires {when(selected.handoff.expires_at)}. Renewing invalidates the previous link.</p>}
      {link && <><input aria-label="Restricted responder link" readOnly value={link} /><div className="map-actions"><button onClick={async () => setNotice(await copyText(link) ? 'Map link copied' : 'Select and copy the link above')}>Copy map link</button><a href={link} target="_blank" rel="noreferrer">Open demo responder view ↗</a></div></>}
    </>}
    <button className="map-config-toggle" onClick={() => setShowConfig(!showConfig)}>{showConfig ? 'Hide' : 'Configure'} camera location & train demo</button>
    {showConfig && event && <div className="map-config">
      <p className="map-caption">Configure camera {event.camera_id} for future detections and add location context to this incident. Its detection snapshot stays unchanged.</p>
      <label>Camera type<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="platform">Platform camera</option><option value="train">Train camera · simulated DEMO-T1</option></select></label>
      <label>Station<select value={stationId} onChange={(e) => setStationId(e.target.value)}><option value="">Location unavailable</option>{stations.map((s) => <option key={s.properties.PT_ID} value={s.properties.PT_ID}>{s.properties.PT_NAME}</option>)}</select></label>
      <label>Platform label<input value={platform} onChange={(e) => setPlatform(e.target.value)} placeholder="Optional; staff-provided" /></label>
      <label>Direction<input value={direction} onChange={(e) => setDirection(e.target.value)} /></label>
      {kind === 'platform' && <label>Line<input value={line} onChange={(e) => setLine(e.target.value)} placeholder="Optional; configured line" /></label>}
      {kind === 'train' && <label>Car ID<input value={car} onChange={(e) => setCar(e.target.value)} /></label>}
      <label>Meeting point description<input value={meeting} onChange={(e) => setMeeting(e.target.value)} placeholder="Only enter a verified meeting point" /></label>
      <label className="map-check"><input type="checkbox" checked={verified} onChange={(e) => setVerified(e.target.checked)} /> Staff verified this meeting point</label>
      <div className="map-actions"><button disabled={Boolean(meeting) && !verified} onClick={async () => {
        const metadata = location()
        const saved = await command(`/maps/cameras/${encodeURIComponent(event.camera_id)}`, 'PUT', metadata)
        if (saved && await command(`/maps/events/${selectedId}/location`, 'PUT', saved)) setNotice('Camera configured; incident context added without changing its snapshot')
      }}>Save location</button>
      <button disabled={!stationId} onClick={async () => {
        if (await command(`/maps/events/${selectedId}/transfer`, 'POST', { location: { ...location(), kind: 'platform', train_id: null, car_id: null, source: 'configured' } })) setNotice('Staff-confirmed transfer recorded; incident status unchanged')
      }}>Confirm transfer to selected platform</button></div>
      <p className="map-caption">Station points are approximate. No platform or entrance coordinates are invented.</p>
      <p><strong>Simulated train DEMO-T1</strong> · {simMode}</p><p className="map-caption">Synthetic movement: Union → King → Queen → Dundas and back. No live subway feed.</p>
      <div className="map-actions">{[['running', 'Start / reconnect'], ['paused', 'Pause movement'], ['disconnected', 'Disconnect telemetry']].map(([mode, label]) => <button key={mode} onClick={async () => { const r = await command('/maps/simulator', 'POST', { mode }); if (r) setSimMode(r.mode) }}>{label}</button>)}</div>
    </div>}
    {notice && <p role="status" className="map-notice">{notice}</p>}{error && <p role="alert" className="map-warning">{error}</p>}
  </aside>
}
