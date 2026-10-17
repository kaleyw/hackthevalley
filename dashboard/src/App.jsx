import { useEffect, useRef, useState } from 'react'

const STATUS_STYLES = {
  open: 'bg-red-100 text-red-800',
  acknowledged: 'bg-amber-100 text-amber-800',
  escalated: 'bg-purple-100 text-purple-800',
  resolved: 'bg-green-100 text-green-800',
  dismissed: 'bg-slate-200 text-slate-700',
}

// Which buttons to show for each status (mirrors TRANSITIONS in backend/app/main.py)
const ACTIONS = {
  open: ['acknowledge', 'escalate', 'dismiss'],
  acknowledged: ['resolve', 'escalate', 'dismiss'],
  escalated: ['acknowledge', 'resolve'],
  resolved: [],
  dismissed: [],
}

const URGENCY_STYLES = {
  high: 'bg-red-600 text-white',
  medium: 'bg-orange-100 text-orange-800',
}

const TYPE_LABELS = {
  possible_fall: 'Possible fall, person not getting up',
  person_down: 'Person down and not getting up',
}

const ACTION_LABELS ={ acknowledge: 'Accept', escalate: 'Escalate', dismiss: 'Dismiss', resolve: 'Resolve' }

function beep() {
  try {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    osc.frequency.value = 880
    osc.connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.3)
  } catch {
    // Browsers block audio until the user has clicked the page once
  }
}

function useEvents() {
  const [events, setEvents] = useState([])
  const [connected, setConnected] = useState(false)
  const retry = useRef(null)

  useEffect(() => {
    let ws
    let closed = false

    const load = () => fetch('/api/events').then((r) => r.json()).then(setEvents).catch(() => {})

    const connect = () => {
      ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`)
      ws.onopen = () => {
        setConnected(true)
        load() // catch up on anything missed while disconnected
      }
      ws.onmessage = (msg) => {
        const { kind, event } = JSON.parse(msg.data)
        if (kind === 'created') beep()
        setEvents((prev) => [event, ...prev.filter((e) => e.id !== event.id)].sort((a, b) => b.id - a.id))
      }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retry.current = setTimeout(connect, 2000)
      }
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retry.current)
      ws?.close()
    }
  }, [])

  return { events, connected }
}

function EventCard({ event, responder }) {
  const [showLog, setShowLog] = useState(false)
  const [error, setError] = useState(null)

  const act = async (action) => {
    let reason
    if (action === 'dismiss') {
      reason = prompt('Why are you dismissing this alert?')
      if (!reason) return
    }
    setError(null)
    const r = await fetch(`/api/events/${event.id}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actor: responder || null, reason }),
    })
    if (!r.ok) setError((await r.json()).detail)
  }

  const isOpen = event.status === 'open'
  const { urgency, summary, reasons = [] } = event.details ?? {}
  return (
    <li className={`rounded-xl border bg-white p-4 shadow-sm ${isOpen ? 'border-red-400 ring-2 ring-red-200' : 'border-slate-200'}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-slate-900">
            {isOpen && <span className="mr-2 inline-block h-2.5 w-2.5 animate-pulse rounded-full bg-red-500" />}
            {summary ?? TYPE_LABELS[event.type] ?? 'Person may need help'}
          </p>
          <p className="text-sm text-slate-600">{event.location} · {event.camera_id} · person #{event.track_id ?? '?'}</p>
          <p className="text-sm text-slate-500">{new Date(event.detected_at).toLocaleTimeString()}</p>
        </div>
        <div className="flex gap-1.5">
          {urgency && (
            <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${URGENCY_STYLES[urgency] ?? URGENCY_STYLES.medium}`}>
              {urgency} urgency
            </span>
          )}
          <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_STYLES[event.status]}`}>{event.status}</span>
        </div>
      </div>

      {reasons.length > 0 && (
        <div className="mt-3 rounded-lg bg-slate-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Why this alert</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-700">
            {reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {ACTIONS[event.status].map((a) => (
          <button
            key={a}
            onClick={() => act(a)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
              a === 'acknowledge' ? 'bg-slate-900 text-white hover:bg-slate-700' : 'border border-slate-300 hover:bg-slate-50'
            }`}
          >
            {ACTION_LABELS[a]}
          </button>
        ))}
        <button onClick={() => setShowLog(!showLog)} className="ml-auto text-sm text-slate-500 hover:text-slate-800">
          {showLog ? 'Hide history' : 'History'}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      {showLog && (
        <ol className="mt-3 space-y-1 border-t pt-3 text-sm text-slate-600">
          {event.log.map((l, i) => (
            <li key={i}>
              {new Date(l.at).toLocaleTimeString()}: <b>{l.action}</b>
              {l.actor && ` by ${l.actor}`}
              {l.reason && `: "${l.reason}"`}
            </li>
          ))}
        </ol>
      )}
    </li>
  )
}

export default function App() {
  const { events, connected } = useEvents()
  const [responder, setResponder] = useState(() => {
    try { return localStorage.getItem('responder') || '' } catch { return '' }
  })

  const saveResponder = (v) => {
    setResponder(v)
    try { localStorage.setItem('responder', v) } catch { /* private mode */ }
  }

  const active = events.filter((e) => ['open', 'acknowledged', 'escalated'].includes(e.status))
  const past = events.filter((e) => !active.includes(e))

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 px-4 py-4">
          <h1 className="text-xl font-bold text-slate-900">Fall Alerts</h1>
          <div className="flex items-center gap-3 text-sm">
            <input
              value={responder}
              onChange={(e) => saveResponder(e.target.value)}
              placeholder="Your name"
              className="w-36 rounded-lg border border-slate-300 px-2 py-1"
            />
            <span className={`flex items-center gap-1.5 ${connected ? 'text-green-700' : 'text-red-600'}`}>
              <span className={`h-2 w-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
              {connected ? 'Live' : 'Reconnecting…'}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-8 px-4 py-6">
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Active ({active.length})</h2>
          {active.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-slate-500">No active alerts</p>
          ) : (
            <ul className="space-y-3">{active.map((e) => <EventCard key={e.id} event={e} responder={responder} />)}</ul>
          )}
        </section>
        {past.length > 0 && (
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">History</h2>
            <ul className="space-y-3">{past.map((e) => <EventCard key={e.id} event={e} responder={responder} />)}</ul>
          </section>
        )}
      </main>
    </div>
  )
}
