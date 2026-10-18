import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import IncidentMapPanel, { MapBoundary } from './IncidentMap.jsx'
import Icon from './Icon.jsx'

const STATUS_LABELS = {
  open: 'Waiting for responder',
  acknowledged: 'Responder on the way',
  on_scene: 'Responder on scene',
  resolved: 'Resolved',
  dismissed: 'Dismissed',
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

// Ding once when something needs security's attention: a new alert, an alert escalating
// to backup, or a camera going offline.
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

const stamp = (iso) => new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

function ageOf(iso, now) {
  const days = (now - new Date(iso)) / 864e5
  if (new Date(iso).toDateString() === new Date(now).toDateString()) return 'today'
  return days <= 7 ? 'week' : days <= 30 ? 'month' : 'older'
}

const RANGES = {
  all: () => true,
  today: (age) => age === 'today',
  week: (age) => ['today', 'week'].includes(age),
  month: (age) => ['today', 'week', 'month'].includes(age),
}

function Button({ children, variant = 'secondary', className = '', ...props }) {
  return (
    <button className={`button button--${variant} ${className}`} type="button" {...props}>
      {children}
    </button>
  )
}

function Chip({ children, tone }) {
  return <span className={`chip ${tone ? `chip--${tone}` : ''}`}>{children}</span>
}

function SectionLabel({ children }) {
  return <div className="section-label">{children}</div>
}

function Header({ view, onViewChange, activeCount, responder, onResponder, sound, cameras, connected }) {
  return (
    <header className="header">
      <div>
        <div className="eyebrow">Response desk</div>
        <h1 className="brand">HEADS-UP</h1>
      </div>
      <nav aria-label="Views" className={`view-tabs view-tabs--${view}`}>
        {[
          ['active', 'Active'],
          ['resolved', 'Resolved'],
          ['map', 'Map'],
        ].map(([id, label]) => (
          <button className={view === id ? 'is-active' : ''} key={id} onClick={() => onViewChange(id)} type="button">
            {label}
            {id === 'active' && activeCount > 0 && <span>{activeCount}</span>}
          </button>
        ))}
      </nav>
      <div className="header-meta">
        <label className="responder-field">
          <span>Responder</span>
          <input aria-label="Responder name" onChange={(e) => onResponder(e.target.value)} placeholder="Your name" value={responder} />
        </label>
        <button
          className={`button sound-toggle ${sound.muted ? 'is-muted' : ''}`}
          onClick={() => sound.setMuted(!sound.muted)}
          title="Alert sounds for security"
          type="button"
        >
          <Icon name={sound.muted ? 'bellOff' : 'bell'} size={14} />
          {sound.muted ? 'Muted' : 'Sound on'}
        </button>
        {cameras.map((c) => (
          <div className={`camera-status ${c.online ? '' : 'is-offline'}`} key={c.id} title={c.location}>
            <span className={`status-dot ${c.online ? 'status-dot--dark' : 'status-dot--offline'}`} />
            <span>{c.id}</span>
          </div>
        ))}
        <div className={`live-status ${connected ? '' : 'is-offline'}`}>
          <span className={`status-dot ${connected ? 'status-dot--live' : 'status-dot--offline'}`} />
          <span>{connected ? 'Live' : 'Reconnecting…'}</span>
        </div>
      </div>
    </header>
  )
}

function StatsSidebar({ stats, open, onToggle }) {
  const has = stats && stats.total > 0
  const tiles = has
    ? [
        {
          label: 'Help reached the person',
          value: stats.help_reached_pct == null ? '–' : `${stats.help_reached_pct}%`,
          detail: `${stats.help_reached} of ${stats.total - stats.dismissed} real alerts`,
        },
        { label: 'Median time to help', value: duration(stats.median_down_to_help_s), detail: 'from going down to someone with them' },
        { label: 'Camera-verified', value: stats.camera_verified, detail: 'help confirmed on camera' },
        { label: 'Escalated', value: stats.escalated, detail: `${stats.dismissed} dismissed as false alarms` },
      ]
    : []
  return (
    <aside className={`stats-sidebar ${open ? 'is-open' : 'is-closed'}`}>
      <div className="stats-sidebar-head">
        {open && <span>Overview</span>}
        <button aria-label={open ? 'Collapse overview' : 'Expand overview'} onClick={onToggle} type="button">
          <Icon name="chevron" />
        </button>
      </div>
      {open && (has ? (
        <div className="side-stats">
          {tiles.map((t) => (
            <div className="side-stat" key={t.label}>
              <div className="stat-label">{t.label}</div>
              <div className="stat-value">{t.value}</div>
              <div className="stat-detail">{t.detail}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="stats-empty">Stats appear after the first alert.</div>
      ))}
    </aside>
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
    <div aria-label="Alert progress" className="timeline">
      {steps.map((s, i) => {
        const done = Boolean(s.at)
        return (
          <div className={`timeline-step ${done ? 'is-done' : ''}`} key={s.label}>
            <div className="timeline-track">
              <span className={`timeline-dot ${done ? 'is-done' : ''}`}>{done ? <Icon name="check" size={10} /> : i + 1}</span>
              {i < steps.length - 1 && <span className={`timeline-line ${done && steps[i + 1].at ? 'is-done' : ''}`} />}
            </div>
            <div className="timeline-label">{s.label}</div>
            <div className="timeline-time">{done ? (s.at === start ? clock(s.at) : `+${duration(secondsBetween(start, s.at))}`) : '—'}</div>
          </div>
        )
      })}
    </div>
  )
}

function WhyAlert({ reasons }) {
  const [open, setOpen] = useState(false)
  if (!reasons.length) return null
  return (
    <div className={`why-disclosure ${open ? 'is-open' : ''}`}>
      <button aria-expanded={open} onClick={() => setOpen(!open)} type="button">
        <span>Why this alert</span>
        <span className="why-summary">{reasons.length} detection signal{reasons.length > 1 ? 's' : ''}</span>
        <Icon name="chevron" />
      </button>
      {open && <ul>{reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
    </div>
  )
}

function HistoryLog({ log }) {
  return (
    <ol className="history-log">
      {log.map((l, i) => (
        <li key={i}>
          <time>{clock(l.at)}</time>: <b>{l.action}</b>
          {l.actor && ` by ${l.actor}`}
          {l.reason && `: "${l.reason}"`}
        </li>
      ))}
    </ol>
  )
}

// Everything the card says about an alert besides its headline: speaker, got-up, escalation, camera help, outcome
function SignalChips({ event, post, setError }) {
  const active = ACTIVE.includes(event.status)
  // Mirrors needs_announcing in backend/app/speaker.py
  const announcing = active && !event.speaker_silenced && !event.arrived_at && !event.help_detected_at && !event.got_up_at
  const gotUp = active && event.got_up_at
  if (!(announcing || gotUp || event.escalation_level > 0 || event.help_detected_at || event.outcome)) return null
  return (
    <div className="signal-chips">
      {announcing && (
        <Chip>
          <Icon name="volume" size={13} /> Speaker asking bystanders to help
          <button className="chip-action" onClick={async () => setError(await post(event.id, 'silence'))} type="button">Silence</button>
        </Chip>
      )}
      {gotUp && <Chip tone="red"><Icon name="person" size={13} /> Person got back up at {clock(event.got_up_at)}. Still check on them</Chip>}
      {event.escalation_level > 0 && <Chip tone="red"><Icon name="warning" size={13} /> {ESCALATION_LABELS[event.escalation_level]}</Chip>}
      {event.help_detected_at && <Chip><Icon name="check" size={13} /> Camera: someone is with them</Chip>}
      {event.outcome && <Chip>Outcome: {OUTCOMES[event.outcome]}</Chip>}
    </div>
  )
}

function AlertCard({ event, cameraOnline, now, post, onDismiss, onResolve, onMap }) {
  const [showLog, setShowLog] = useState(false)
  const [error, setError] = useState(null)
  const isOpen = event.status === 'open'
  const { urgency, summary, reasons = [] } = event.details ?? {}
  const downFor = (now - new Date(event.went_down_at ?? event.created_at)) / 1000
  const [primary, ...rest] = ACTIONS[event.status].filter((a) => a !== 'escalate' || event.escalation_level < 2)

  const act = async (action) => {
    if (action === 'resolve') return onResolve(event)
    if (action === 'dismiss') return onDismiss(event)
    setError(await post(event.id, action))
  }

  return (
    <article className={`alert-card ${isOpen ? 'alert-card--high' : 'alert-card--medium'}`} id={`incident-${event.id}`}>
      <div className="alert-card-content">
        <div className="alert-head">
          <div className="alert-copy">
            <div className="alert-title-row">
              <div className="alert-title">{summary ?? TYPE_LABELS[event.type] ?? 'Person may need help'}</div>
            </div>
            <div className="alert-location">{event.location} · {event.camera_id} · person #{event.track_id ?? '?'}</div>
          </div>
          {urgency && <div className="alert-badges"><Chip tone={urgency === 'high' ? 'solid' : undefined}>{urgency} urgency</Chip></div>}
        </div>

        <div className="alert-priority">
          <div className="timer">Down for {duration(downFor)}</div>
          <div className="alert-status">
            <span className={`alert-status-dot ${isOpen ? 'alert-status-dot--pulse' : ''}`} />
            {STATUS_LABELS[event.status]}
          </div>
          {primary && <Button onClick={() => act(primary)} variant="primary">{ACTION_LABELS[primary]}</Button>}
        </div>

        <SignalChips event={event} post={post} setError={setError} />
        <Timeline event={event} />
        <WhyAlert reasons={reasons} />

        <div className="actions">
          <div className="actions-links">
            <Button onClick={() => onMap(event.id)}>View on map</Button>
            <Button onClick={() => setShowLog(!showLog)}>{showLog ? 'Hide history' : 'History'}</Button>
          </div>
          <div className="action-group">
            {rest.map((a) => (
              <Button className={a === 'dismiss' ? '' : 'button--outline'} key={a} onClick={() => act(a)}>{ACTION_LABELS[a]}</Button>
            ))}
          </div>
        </div>
        {error && <p className="form-error">{error}</p>}
        {showLog && <HistoryLog log={event.log} />}
      </div>
      <CameraPanel cameraId={event.camera_id} online={cameraOnline} />
    </article>
  )
}

// Live preview from vision/run.py (camera picture with the pose skeleton drawn on top). Falls back to the
// placeholder when the camera is offline or the stream can't be reached, and retries on its own.
function CameraPanel({ cameraId, online }) {
  const [failed, setFailed] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const live = online && !failed

  useEffect(() => {
    if (!failed) return undefined
    const id = setTimeout(() => setFailed(false), 5000)
    return () => clearTimeout(id)
  }, [failed])

  useEffect(() => {
    if (!expanded) return undefined
    const onKey = (e) => e.key === 'Escape' && setExpanded(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  const feed = <img alt={`Live view from ${cameraId}`} onError={() => setFailed(true)} src="/camera/stream.mjpg" />

  return (
    <aside aria-label="Live camera" className="camera-placeholder">
      <div className="camera-placeholder-head">
        <span><span className={`camera-live-dot ${live ? 'camera-live-dot--on' : ''}`} /> {live ? 'Live camera' : 'Camera offline'}</span>
        <strong>{cameraId}</strong>
      </div>
      <div className="camera-stage">
        {live && feed}
        <button aria-label="Expand camera preview" className="camera-expand" disabled={!live} onClick={() => setExpanded(true)} type="button">
          <Icon name="expand" />
        </button>
        {!live && (
          <>
            <span className="camera-stage-icon"><Icon name="camera" size={24} /></span>
            <strong>{online ? 'Reconnecting to camera…' : 'No live feed'}</strong>
            <span>{online ? 'The preview will return on its own' : 'Start vision/run.py to see the camera here'}</span>
          </>
        )}
      </div>
      {expanded && live && (
        <div className="camera-lightbox" onMouseDown={(e) => e.target === e.currentTarget && setExpanded(false)} role="presentation">
          <div aria-label={`Live view from ${cameraId}`} aria-modal="true" className="camera-lightbox-body" role="dialog">
            {feed}
            <button aria-label="Close camera preview" className="camera-lightbox-close" onClick={() => setExpanded(false)} type="button">
              <Icon name="close" />
            </button>
          </div>
        </div>
      )}
    </aside>
  )
}

function ActiveView({ active, cameras, now, post, onDismiss, onResolve, onMap }) {
  // One list in a fixed order (newest alert first), so a card stays where it is when its status changes
  const card = (e) => <AlertCard cameraOnline={Boolean(cameras.find((c) => c.id === e.camera_id)?.online)} event={e} key={e.id} now={now} onDismiss={onDismiss} onMap={onMap} onResolve={onResolve} post={post} />
  if (active.length === 0) return <div className="empty-state">No active alerts</div>
  return (
    <>
      <SectionLabel>ACTIVE ALERTS ({active.length})</SectionLabel>
      {active.map(card)}
    </>
  )
}

function ResolvedRow({ event, post, onMap }) {
  const [open, setOpen] = useState(false)
  const [error, setError] = useState(null)
  const dismissed = event.status === 'dismissed'
  const at = event.resolved_at ?? event.created_at
  const reasonText = dismissed ? [...event.log].reverse().find((l) => l.reason)?.reason : null
  const helpAt = [event.arrived_at, event.help_detected_at].filter(Boolean).sort()[0] ?? event.acknowledged_at
  const response = secondsBetween(event.went_down_at ?? event.created_at, helpAt)
  const { summary, reasons = [] } = event.details ?? {}
  return (
    <article className={`resolved-item ${open ? 'is-open' : ''}`}>
      <button aria-expanded={open} className="resolved-row" onClick={() => setOpen(!open)} type="button">
        <span className={`resolved-check ${dismissed ? 'resolved-check--dismissed' : ''}`}><Icon name={dismissed ? 'close' : 'check'} /></span>
        <div className="resolved-main">
          <strong>{dismissed ? `Dismissed${reasonText ? `: ${reasonText}` : ''}` : OUTCOMES[event.outcome] ?? 'Resolved'}</strong>
          <span>{event.location} · {event.camera_id}</span>
        </div>
        <div className="resolved-meta">
          <strong>{stamp(at)}</strong>
          <span>{response == null ? (dismissed ? 'No response needed' : 'No response logged') : `Response ${duration(response)}`}</span>
        </div>
        <span className="resolved-chevron"><Icon name="chevron" /></span>
      </button>
      {open && (
        <div className="resolved-detail">
          <div className="alert-location" style={{ marginBottom: 14 }}>
            {summary ?? TYPE_LABELS[event.type] ?? 'Person may need help'} · person #{event.track_id ?? '?'}
          </div>
          <SignalChips event={event} post={post} setError={setError} />
          <Timeline event={event} />
          <WhyAlert reasons={reasons} />
          <div className="actions">
            <div className="actions-links">
              <Button onClick={() => onMap(event.id)}>View on map</Button>
            </div>
          </div>
          {error && <p className="form-error">{error}</p>}
          <HistoryLog log={event.log} />
        </div>
      )}
    </article>
  )
}

function ResolvedView({ past, now, post, onMap }) {
  const [range, setRange] = useState('all')
  const [query, setQuery] = useState('')
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return past.filter((e) => {
      const at = e.resolved_at ?? e.created_at
      if (!RANGES[range](ageOf(at, now))) return false
      const reason = [...e.log].reverse().find((l) => l.reason)?.reason ?? ''
      const text = `${OUTCOMES[e.outcome] ?? ''} ${e.status} ${e.location} ${e.camera_id} ${stamp(at)} ${reason}`.toLowerCase()
      return text.includes(q)
    })
  }, [past, query, range, now])

  return (
    <>
      <div className="resolved-toolbar">
        <div>
          <SectionLabel>RESOLVED ALERTS</SectionLabel>
          <div className="resolved-count">{filtered.length} record{filtered.length === 1 ? '' : 's'}</div>
        </div>
        <div className="filters">
          <label className="search-field">
            <Icon name="search" />
            <input aria-label="Search resolved alerts" onChange={(e) => setQuery(e.target.value)} placeholder="Search place, camera or outcome" value={query} />
          </label>
          <label className="range-field">
            <select aria-label="Filter by time" onChange={(e) => setRange(e.target.value)} value={range}>
              <option value="all">All time</option>
              <option value="today">Today</option>
              <option value="week">Last 7 days</option>
              <option value="month">Last 30 days</option>
            </select>
          </label>
        </div>
      </div>
      <div className="resolved-list">
        {filtered.map((e) => <ResolvedRow event={e} key={e.id} onMap={onMap} post={post} />)}
        {filtered.length === 0 && <div className="no-results">{past.length ? 'No resolved alerts match these filters.' : 'Nothing resolved yet.'}</div>}
      </div>
    </>
  )
}

function Modal({ eyebrow, title, copy, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()} role="presentation">
      <div aria-labelledby="modal-title" aria-modal="true" className="modal" role="dialog">
        <div className="eyebrow">{eyebrow}</div>
        <div className="modal-title" id="modal-title">{title}</div>
        <div className="modal-copy">{copy}</div>
        {children}
      </div>
    </div>
  )
}

function DismissModal({ event, onClose, onSubmit }) {
  const [reason, setReason] = useState('')
  const [error, setError] = useState(null)
  const submit = async () => {
    const err = await onSubmit(event, reason.trim())
    if (err) setError(err)
    else onClose()
  }
  return (
    <Modal copy="A reason is required. This helps responders review future detections." eyebrow={`Dismiss alert #${event.id}`} onClose={onClose} title="Why is this not an alert?">
      <label className="text-field">
        <span>Reason</span>
        <textarea autoFocus onChange={(e) => setReason(e.target.value)} placeholder="e.g. Normal floor activity, person was resting" rows={3} value={reason} />
      </label>
      {error && <p className="form-error">{error}</p>}
      <div className="modal-actions">
        <Button onClick={onClose} variant="quiet">Cancel</Button>
        <Button disabled={!reason.trim()} onClick={submit} variant="dark">Dismiss alert</Button>
      </div>
    </Modal>
  )
}

function ResolveModal({ event, onClose, onSubmit }) {
  const [outcome, setOutcome] = useState('')
  const [error, setError] = useState(null)
  const submit = async () => {
    const err = await onSubmit(event, outcome)
    if (err) setError(err)
    else onClose()
  }
  return (
    <Modal copy="Pick the outcome. It is saved with the alert history." eyebrow={`Resolve alert #${event.id}`} onClose={onClose} title="What happened?">
      <label className="text-field">
        <span>Outcome</span>
        <select autoFocus onChange={(e) => setOutcome(e.target.value)} value={outcome}>
          <option value="">Choose an outcome</option>
          {Object.entries(OUTCOMES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </label>
      {error && <p className="form-error">{error}</p>}
      <div className="modal-actions">
        <Button onClick={onClose} variant="quiet">Cancel</Button>
        <Button disabled={!outcome} onClick={submit} variant="dark">Save outcome</Button>
      </div>
    </Modal>
  )
}

export default function App() {
  const { events, cameras, stats, connected } = useLiveData()
  const now = useNow()
  const sound = useAlertSound()
  useSecurityDings(events, cameras, sound.play)
  const [view, setView] = useState('active')
  const [statsOpen, setStatsOpen] = useState(true)
  const [modal, setModal] = useState(null) // { kind: 'dismiss' | 'resolve', event }
  const [selectedId, setSelectedId] = useState(null)
  const newestId = useRef(null)
  useEffect(() => {
    // Follow the newest active alert; old resolved/dismissed ones aren't auto-selected
    const newest = events.find((e) => ACTIVE.includes(e.status))
    if (newest && newestId.current !== newest.id) {
      newestId.current = newest.id
      setSelectedId(newest.id)
    }
  }, [events])
  const showOnMap = (id) => {
    setSelectedId(id)
    setView('map')
  }
  const [responder, setResponder] = useState(() => {
    try { return localStorage.getItem('responder') || '' } catch { return '' }
  })

  const saveResponder = (v) => {
    setResponder(v)
    try { localStorage.setItem('responder', v) } catch { /* private mode */ }
  }

  // Returns an error message, or null when it worked
  const post = useCallback(async (id, action, extra = {}) => {
    try {
      const r = await fetch(`/api/events/${id}/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor: responder || null, ...extra }),
      })
      if (r.ok) return null
      const detail = (await r.json()).detail
      return typeof detail === 'string' ? detail : 'Something went wrong'
    } catch {
      return 'Could not reach the server'
    }
  }, [responder])

  const active = events.filter((e) => ACTIVE.includes(e.status))
  const past = events.filter((e) => !ACTIVE.includes(e.status))
  const offline = cameras.filter((c) => !c.online)

  return (
    <div className="app-shell">
      <div className="workspace">
        <Header activeCount={active.length} cameras={cameras} connected={connected} onResponder={saveResponder} onViewChange={setView} responder={responder} sound={sound} view={view} />

        {!sound.enabled && (
          <button className="notice-bar" style={{ marginTop: 24, marginBottom: 0 }} type="button">
            <Icon name="bell" /> <span><b>Alert sounds are off.</b> Click here once to turn them on, so you hear new alerts.</span>
          </button>
        )}
        {offline.length > 0 && (
          <div className="notice-bar notice-bar--alert" role="alert" style={{ marginTop: 24, marginBottom: 0 }}>
            <Icon name="warning" />
            <span><b>Camera offline:</b> {offline.map((c) => `${c.id} (${c.location})`).join(', ')}. No alerts can come from it until it's back.</span>
          </div>
        )}

        {view === 'active' && (
          <main className="dashboard dashboard--active">
            <ActiveView active={active} cameras={cameras} now={now} onDismiss={(event) => setModal({ kind: 'dismiss', event })} onMap={showOnMap} onResolve={(event) => setModal({ kind: 'resolve', event })} post={post} />
          </main>
        )}
        {view === 'resolved' && (
          <div className={`content-layout ${statsOpen ? '' : 'stats-collapsed'}`}>
            <StatsSidebar onToggle={() => setStatsOpen(!statsOpen)} open={statsOpen} stats={stats} />
            <main className="dashboard">
              <ResolvedView now={now} onMap={showOnMap} past={past} post={post} />
            </main>
          </div>
        )}
        {view === 'map' && (
          <main className="dashboard dashboard--map">
            <MapBoundary>
              <IncidentMapPanel connected={connected} events={events} onSelect={setSelectedId} selectedId={selectedId} />
            </MapBoundary>
          </main>
        )}
      </div>
      {modal?.kind === 'dismiss' && (
        <DismissModal event={modal.event} onClose={() => setModal(null)} onSubmit={(e, reason) => post(e.id, 'dismiss', { reason })} />
      )}
      {modal?.kind === 'resolve' && (
        <ResolveModal event={modal.event} onClose={() => setModal(null)} onSubmit={(e, outcome) => post(e.id, 'resolve', { outcome })} />
      )}
    </div>
  )
}
