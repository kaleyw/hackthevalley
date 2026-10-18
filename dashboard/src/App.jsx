import { useCallback, useEffect, useRef, useState } from 'react'
import IncidentMapPanel, { MapBoundary } from './IncidentMap.jsx'

const STATUS = {
  open: { label: 'Waiting for responder', style: 'bg-red-100 text-red-800' },
  acknowledged: { label: 'Responder on the way', style: 'bg-amber-100 text-amber-800' },
  on_scene: { label: 'Responder on scene', style: 'bg-blue-100 text-blue-800' },
  resolved: { label: 'Resolved', style: 'bg-green-100 text-green-800' },
  dismissed: { label: 'Dismissed', style: 'bg-slate-200 text-slate-700' },
}

// Which buttons to show for each status (mirrors TRANSITIONS in backend/app/main.py)
const ACTIONS = {
  open: ['acknowledge', 'arrive', 'escalate', 'dismiss'],
  acknowledged: ['arrive', 'escalate', 'dismiss'],
  on_scene: ['resolve', 'dismiss'],
  resolved: [],
  dismissed: [],
}

const ACTION_LABELS = {
  acknowledge: "Accept, I'm going",
  arrive: "I'm here",
  escalate: 'Escalate',
  dismiss: 'Dismiss',
  resolve: 'Resolve',
}

// Mirrors OUTCOMES in backend/app/main.py
const OUTCOMES = {
  person_ok: 'Person OK, no help needed',
  helped_on_site: 'Helped on site',
  medical_help_called: 'Medical help called',
  person_gone: 'Person gone when we arrived',
}

const URGENCY_STYLES = {
  high: 'bg-red-600 text-white',
  medium: 'bg-orange-100 text-orange-800',
}

const TYPE_LABELS = {
  possible_fall: 'Possible fall, person not getting up',
  person_down: 'Person down and not getting up',
}

const ESCALATION_LABELS = { 1: 'Backup responder notified', 2: 'Supervisor notified' }

const ACTIVE = ['open', 'acknowledged', 'on_scene']

// Alert sounds for security: [frequency Hz, seconds] notes
const SOUNDS = {
  newAlert: [[880, 0.18], [1175, 0.35]],                          // ding-dong
  escalated: [[1175, 0.12], [1175, 0.12], [1175, 0.12], [1568, 0.4]],  // urgent
  cameraOffline: [[440, 0.4], [330, 0.6]],                         // low warning
}
const REPEAT_DING_MS = 5000  // keep dinging while any alert is waiting for someone to accept it

// Browsers only allow sound after the user has clicked the page, so sound starts "off"
// until the first click anywhere.
function useAlertSound() {
  const ctxRef = useRef(null)
  const mutedRef = useRef(false)
  const [enabled, setEnabled] = useState(false)
  const [muted, setMutedState] = useState(false)

  useEffect(() => {
    const enable = () => {
      try {
        ctxRef.current ??= new AudioContext()
        ctxRef.current.resume().then(() => setEnabled(ctxRef.current.state === 'running'))
      } catch {
        // No Web Audio support; stay silent
      }
    }
    window.addEventListener('pointerdown', enable)
    return () => window.removeEventListener('pointerdown', enable)
  }, [])

  const setMuted = (v) => {
    mutedRef.current = v
    setMutedState(v)
  }

  const play = useCallback((notes) => {
    const ctx = ctxRef.current
    if (!ctx || ctx.state !== 'running' || mutedRef.current) return
    let t = ctx.currentTime
    for (const [freq, dur] of notes) {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.frequency.value = freq
      gain.gain.setValueAtTime(0.0001, t)
      gain.gain.exponentialRampToValueAtTime(0.4, t + 0.01)
      gain.gain.exponentialRampToValueAtTime(0.0001, t + dur)
      osc.connect(gain).connect(ctx.destination)
      osc.start(t)
      osc.stop(t + dur)
      t += dur + 0.06
    }
  }, [])

  return { enabled, muted, setMuted, play }
}

// Ding when something needs security's attention: a new alert (repeating until accepted),
// an alert escalating to backup, or a camera going offline.
function useSecurityDings(events, cameras, play) {
  const seen = useRef(null)

  useEffect(() => {
    const prev = seen.current
    seen.current = {
      escalation: Object.fromEntries(events.map((e) => [e.id, e.escalation_level])),
      online: Object.fromEntries(cameras.map((c) => [c.id, c.online])),
    }
    if (!prev) return // first load: don't ding for what was already there
    if (events.some((e) => !(e.id in prev.escalation) && e.status === 'open')) play(SOUNDS.newAlert)
    else if (events.some((e) => e.escalation_level > (prev.escalation[e.id] ?? 0))) play(SOUNDS.escalated)
    if (cameras.some((c) => !c.online && prev.online[c.id] !== false)) play(SOUNDS.cameraOffline)
  }, [events, cameras, play])

  const waiting = events.filter((e) => e.status === 'open')
  const anyEscalated = waiting.some((e) => e.escalation_level > 0)
  useEffect(() => {
    if (waiting.length === 0) return
    const id = setInterval(() => play(anyEscalated ? SOUNDS.escalated : SOUNDS.newAlert), REPEAT_DING_MS)
    return () => clearInterval(id)
  }, [waiting.length, anyEscalated, play])
}

function duration(seconds) {
  if (seconds == null) return '–'
  const s = Math.max(0, Math.round(seconds))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}

const secondsBetween = (a, b) => (a && b ? (new Date(b) - new Date(a)) / 1000 : null)
const clock = (iso) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

function useLiveData() {
  const [events, setEvents] = useState([])
  const [cameras, setCameras] = useState([])
  const [stats, setStats] = useState(null)
  const [connected, setConnected] = useState(false)
  const retry = useRef(null)

  const loadStats = useCallback(() => fetch('/api/stats').then((r) => r.json()).then(setStats).catch(() => {}), [])

  useEffect(() => {
    let ws
    let closed = false

    const loadAll = () => {
      fetch('/api/events').then((r) => r.json()).then(setEvents).catch(() => {})
      fetch('/api/cameras').then((r) => r.json()).then(setCameras).catch(() => {})
      loadStats()
    }

    const connect = () => {
      ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`)
      ws.onopen = () => {
        setConnected(true)
        loadAll() // catch up on anything missed while disconnected
      }
      ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data)
        if (data.kind === 'cameras') {
          setCameras(data.cameras)
          return
        }
        setEvents((prev) => [data.event, ...prev.filter((e) => e.id !== data.event.id)].sort((a, b) => b.id - a.id))
        loadStats()
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
  }, [loadStats])

  return { events, cameras, stats, connected }
}

function StatsBar({ stats }) {
  if (!stats || stats.total === 0) return null
  const tiles = [
    {
      label: 'Help reached the person',
      value: stats.help_reached_pct == null ? '–' : `${stats.help_reached_pct}%`,
      sub: `${stats.help_reached} of ${stats.total - stats.dismissed} real alerts`,
      highlight: true,
    },
    { label: 'Median time to help', value: duration(stats.median_down_to_help_s), sub: 'from going down to someone with them' },
    { label: 'Camera-verified', value: stats.camera_verified, sub: 'help confirmed on camera' },
    { label: 'Escalated', value: stats.escalated, sub: `${stats.dismissed} dismissed as false alarms` },
  ]
  return (
    <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className={`rounded-xl border p-3 ${t.highlight ? 'border-green-300 bg-green-50' : 'border-slate-200 bg-white'}`}>
          <p className="text-xs text-slate-500">{t.label}</p>
          <p className="text-2xl font-bold text-slate-900">{t.value}</p>
          <p className="text-xs text-slate-500">{t.sub}</p>
        </div>
      ))}
    </section>
  )
}

function Timeline({ event }) {
  const start = event.went_down_at ?? event.created_at
  const help = [event.arrived_at, event.help_detected_at].filter(Boolean).sort()[0]
  const steps = [
    { label: 'Went down', at: event.went_down_at },
    { label: 'Alert sent', at: event.created_at },
    { label: `Accepted${event.assigned_to ? ` (${event.assigned_to})` : ''}`, at: event.acknowledged_at },
    { label: event.arrived_at || !help ? 'Help reached them' : 'Someone with them (camera)', at: help },
    { label: event.status === 'dismissed' ? 'Dismissed' : 'Resolved', at: event.resolved_at },
  ]
  return (
    <ol className="mt-3 grid grid-cols-5 gap-1 text-center text-xs">
      {steps.map((s) => (
        <li key={s.label} className={`rounded-md px-1 py-1.5 ${s.at ? 'bg-slate-800 text-white' : 'bg-slate-100 text-slate-400'}`}>
          <p className="font-medium leading-tight">{s.label}</p>
          <p className="mt-0.5 tabular-nums opacity-80">{s.at ? (s.at === start ? clock(s.at) : `+${duration(secondsBetween(start, s.at))}`) : '–'}</p>
        </li>
      ))}
    </ol>
  )
}

function EventCard({ event, responder, now, onMap }) {
  const [showLog, setShowLog] = useState(false)
  const [resolving, setResolving] = useState(false)
  const [outcome, setOutcome] = useState('')
  const [error, setError] = useState(null)

  const post = async (action, extra = {}) => {
    setError(null)
    const r = await fetch(`/api/events/${event.id}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actor: responder || null, ...extra }),
    })
    if (!r.ok) setError((await r.json()).detail)
    return r.ok
  }

  const act = async (action) => {
    if (action === 'resolve') return setResolving(true)
    if (action === 'dismiss') {
      const reason = prompt('Why are you dismissing this alert? (e.g. false alarm, person was resting)')
      if (reason) await post('dismiss', { reason })
      return
    }
    await post(action)
  }

  const active = ACTIVE.includes(event.status)
  const isOpen = event.status === 'open'
  const { urgency, summary, reasons = [] } = event.details ?? {}
  const downFor = (now - new Date(event.went_down_at ?? event.created_at)) / 1000
  // Mirrors needs_announcing in backend/app/speaker.py
  const announcing = active && !event.speaker_silenced && !event.arrived_at && !event.help_detected_at && !event.got_up_at
  const gotUp = active && event.got_up_at

  return (
    <li id={`incident-${event.id}`} className={`rounded-xl border bg-white p-4 shadow-sm ${isOpen ? 'border-red-400 ring-2 ring-red-200' : 'border-slate-200'}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold text-slate-900">
            {isOpen && <span className="mr-2 inline-block h-2.5 w-2.5 animate-pulse rounded-full bg-red-500" />}
            {summary ?? TYPE_LABELS[event.type] ?? 'Person may need help'}
          </p>
          <p className="text-sm text-slate-600">{event.location} · {event.camera_id} · person #{event.track_id ?? '?'}</p>
          {active && <p className="text-sm font-medium text-red-700 tabular-nums">Down for {duration(downFor)}</p>}
        </div>
        <div className="flex flex-wrap justify-end gap-1.5">
          {urgency && (
            <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${URGENCY_STYLES[urgency] ?? URGENCY_STYLES.medium}`}>
              {urgency} urgency
            </span>
          )}
          <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${STATUS[event.status].style}`}>
            {STATUS[event.status].label}
          </span>
        </div>
      </div>

      {(announcing || gotUp || event.escalation_level > 0 || event.help_detected_at || event.outcome) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs font-medium">
          {announcing && (
            <span className="flex items-center gap-1.5 rounded-full bg-sky-100 py-1 pl-2.5 pr-1 text-sky-800">
              🔊 Speaker asking bystanders to help
              <button onClick={() => post('silence')} className="rounded-full bg-white px-2 py-0.5 text-sky-900 hover:bg-sky-50">
                Silence
              </button>
            </span>
          )}
          {gotUp && (
            <span className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-900">
              🧍 Person got back up at {clock(event.got_up_at)}. Still check on them
            </span>
          )}
          {event.escalation_level > 0 && (
            <span className="rounded-full bg-purple-100 px-2.5 py-1 text-purple-800">⚠ {ESCALATION_LABELS[event.escalation_level]}</span>
          )}
          {event.help_detected_at && (
            <span className="rounded-full bg-green-100 px-2.5 py-1 text-green-800">✓ Camera: someone is with them</span>
          )}
          {event.outcome && <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">Outcome: {OUTCOMES[event.outcome]}</span>}
        </div>
      )}

      <Timeline event={event} />
      <button onClick={() => onMap(event.id)} className="mt-3 text-sm font-medium text-blue-700 underline">View incident #{event.id} on map</button>

      {reasons.length > 0 && (
        <div className="mt-3 rounded-lg bg-slate-50 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Why this alert</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-700">
            {reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {resolving ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select value={outcome} onChange={(e) => setOutcome(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
            <option value="">What happened?</option>
            {Object.entries(OUTCOMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <button
            disabled={!outcome}
            onClick={async () => (await post('resolve', { outcome })) && setResolving(false)}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
          >
            Save outcome
          </button>
          <button onClick={() => setResolving(false)} className="text-sm text-slate-500">Cancel</button>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {ACTIONS[event.status]
            .filter((a) => a !== 'escalate' || event.escalation_level < 2)
            .map((a, i) => (
              <button
                key={a}
                onClick={() => act(a)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                  i === 0 ? 'bg-slate-900 text-white hover:bg-slate-700' : 'border border-slate-300 hover:bg-slate-50'
                }`}
              >
                {ACTION_LABELS[a]}
              </button>
            ))}
          <button onClick={() => setShowLog(!showLog)} className="ml-auto text-sm text-slate-500 hover:text-slate-800">
            {showLog ? 'Hide history' : 'History'}
          </button>
        </div>
      )}
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}

      {showLog && (
        <ol className="mt-3 space-y-1 border-t pt-3 text-sm text-slate-600">
          {event.log.map((l, i) => (
            <li key={i}>
              {clock(l.at)}: <b>{l.action}</b>
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
  const { events, cameras, stats, connected } = useLiveData()
  const now = useNow()
  const sound = useAlertSound()
  useSecurityDings(events, cameras, sound.play)
  const [selectedId, setSelectedId] = useState(null)
  const newestId = useRef(null)
  useEffect(() => {
    if (events[0] && newestId.current !== events[0].id) {
      newestId.current = events[0].id
      setSelectedId(events[0].id)
    }
  }, [events])
  const selectIncident = (id) => {
    setSelectedId(id)
    document.getElementById(`incident-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
  const [responder, setResponder] = useState(() => {
    try { return localStorage.getItem('responder') || '' } catch { return '' }
  })

  const saveResponder = (v) => {
    setResponder(v)
    try { localStorage.setItem('responder', v) } catch { /* private mode */ }
  }

  const active = events.filter((e) => ACTIVE.includes(e.status))
  const past = events.filter((e) => !ACTIVE.includes(e.status))
  const offline = cameras.filter((c) => !c.online)

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-3 px-4 py-4">
          <h1 className="text-xl font-bold text-slate-900">Collapse Alerts</h1>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <input
              value={responder}
              onChange={(e) => saveResponder(e.target.value)}
              placeholder="Responder name"
              className="w-36 rounded-lg border border-slate-300 px-2 py-1"
            />
            <button
              onClick={() => sound.setMuted(!sound.muted)}
              className={`rounded-lg border px-2 py-1 ${sound.muted ? 'border-red-300 text-red-700' : 'border-slate-300 text-slate-700'}`}
              title="Alert sounds for security"
            >
              {sound.muted ? '🔕 Muted' : '🔔 Sound on'}
            </button>
            {cameras.map((c) => (
              <span key={c.id} className={`flex items-center gap-1.5 ${c.online ? 'text-slate-600' : 'text-red-600'}`} title={c.location}>
                <span className={`h-2 w-2 rounded-full ${c.online ? 'bg-green-500' : 'bg-red-500'}`} />
                {c.id}
              </span>
            ))}
            <span className={`flex items-center gap-1.5 ${connected ? 'text-green-700' : 'text-red-600'}`}>
              <span className={`h-2 w-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
              {connected ? 'Live' : 'Reconnecting…'}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] space-y-6 px-4 py-6">
        {!sound.enabled && (
          <button className="w-full rounded-xl border border-amber-300 bg-amber-50 p-3 text-left text-sm text-amber-900">
            🔔 <b>Alert sounds are off.</b> Click here once to turn them on, so you hear new alerts.
          </button>
        )}
        {offline.length > 0 && (
          <div className="rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-800">
            <b>Camera offline:</b> {offline.map((c) => `${c.id} (${c.location})`).join(', ')}. No alerts can come from it until it's back.
          </div>
        )}

        <StatsBar stats={stats} />

        <div className={events.length ? 'dashboard-map-layout' : ''}>
        <div className="space-y-6">

        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Active ({active.length})</h2>
          {active.length === 0 ? (
            <p className="rounded-xl border border-dashed border-slate-300 p-6 text-center text-slate-500">No active alerts</p>
          ) : (
            <ul className="space-y-3">{active.map((e) => <EventCard key={e.id} event={e} responder={responder} now={now} onMap={selectIncident} />)}</ul>
          )}
        </section>
        {past.length > 0 && (
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">History</h2>
            <ul className="space-y-3">{past.map((e) => <EventCard key={e.id} event={e} responder={responder} now={now} onMap={selectIncident} />)}</ul>
          </section>
        )}
        </div>
        {events.length > 0 && <MapBoundary><IncidentMapPanel events={events} selectedId={selectedId ?? events[0].id} onSelect={selectIncident} connected={connected} /></MapBoundary>}
        </div>
      </main>
    </div>
  )
}
