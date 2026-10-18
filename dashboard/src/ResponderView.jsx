import { useEffect, useState } from 'react'
import { copyText, LocationDetails, MapBoundary, NetworkMap } from './IncidentMap.jsx'

export default function ResponderView({ eventId }) {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token'))
  const [context, setContext] = useState(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  useEffect(() => {
    let closed = false
    const load = async () => {
      try {
        const response = await fetch(`/api/responder/events/${eventId}`, { headers: { 'X-Responder-Token': token ?? '' }, cache: 'no-store', referrerPolicy: 'no-referrer' })
        if (!response.ok) {
          if ([401, 403, 404, 410].includes(response.status) && !closed) setContext(null)
          throw new Error([401, 403, 404, 410].includes(response.status) ? 'This responder link is invalid, expired, or revoked.' : 'Location service unavailable. Showing the last received information.')
        }
        const value = await response.json()
        if (!closed) { setContext(value); setConnected(true); setError('') }
      } catch (e) { if (!closed) { setConnected(false); setError(e.message) } }
    }
    load()
    const timer = setInterval(load, 2000)
    return () => { closed = true; clearInterval(timer) }
  }, [eventId, token])
  return <main className="responder-view">
    <p className="map-eyebrow">RESTRICTED · READ-ONLY · RESPONDER VIEW</p>
    <h1>Incident #{eventId}</h1>
    <p className="map-notice">This page does not place calls or contact emergency services. Opening this link does not tell the control room you've seen it.</p>
    {error && <p role="alert" className="map-warning">{error}</p>}
    {context ? <>
      <MapBoundary><NetworkMap contexts={[context]} selectedId={Number(eventId)} /></MapBoundary>
      <LocationDetails context={context} connected={connected} />
      <div className="map-actions"><button onClick={async () => setNotice(await copyText(context.briefing) ? 'Briefing copied' : 'Select the briefing below to copy it')}>Copy concise location briefing</button></div>
      <textarea readOnly aria-label="Responder location briefing" value={context.briefing} rows={5} />
      {notice && <p role="status">{notice}</p>}
    </> : !error && <p>Checking restricted access…</p>}
  </main>
}
