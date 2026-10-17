"""Detects people who go down and stay down, one state machine per tracked person.

Two ways to trigger an alert:
- Fast fall: hips drop fast and the torso ends up near horizontal, then the person
  stays down for FALL_ALERT_SECONDS -> "possible_fall", high urgency.
- Slow collapse: the person ends up lying down at any speed (slumping, sliding down
  a wall) and stays down for DOWN_ALERT_SECONDS -> "person_down", medium urgency.

States: MONITORING -> DOWN_PENDING -> ALERTED. Being upright for RECOVER_SECONDS
returns to MONITORING. Frames where the hips/shoulders aren't visible are
"uncertain": they never count as lying or as upright, so the state just holds.

Every alert carries plain-language reasons so responders can see why it fired.
"""

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

import config

# COCO keypoint indices used by YOLO pose
L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 5, 6, 11, 12

MONITORING = "monitoring"
DOWN_PENDING = "down_pending"
ALERTED = "alerted"


@dataclass
class Sample:
    t: float
    hip: np.ndarray       # hip midpoint (x, y)
    shoulder: np.ndarray  # shoulder midpoint (x, y)
    torso_len: float
    angle_deg: float      # torso angle from vertical: 0 = upright, 90 = horizontal


@dataclass
class Track:
    state: str = MONITORING
    history: deque = field(default_factory=deque)
    lying_since: float | None = None
    upright_since: float | None = None
    last_seen: float = 0.0
    upright_torso_len: float | None = None  # body-size reference, measured while upright
    fast_drop: dict | None = None           # set if the person went down fast
    frames_while_down: int = 0
    hidden_frames_while_down: int = 0


def measure(t, xy, conf):
    """Return a Sample, or None if the torso keypoints aren't visible enough."""
    idx = [L_SHOULDER, R_SHOULDER, L_HIP, R_HIP]
    if conf is not None and np.min(conf[idx]) < config.KEYPOINT_MIN_CONF:
        return None
    shoulder = (xy[L_SHOULDER] + xy[R_SHOULDER]) / 2
    hip = (xy[L_HIP] + xy[R_HIP]) / 2
    dx, dy = shoulder - hip
    torso_len = math.hypot(dx, dy)
    if torso_len < 1:
        return None
    angle = math.degrees(math.atan2(abs(dx), abs(dy)))
    return Sample(t=t, hip=hip, shoulder=shoulder, torso_len=torso_len, angle_deg=angle)


class FallDetector:
    def __init__(self):
        self.tracks: dict[int, Track] = {}

    def state(self, track_id):
        return self.tracks[track_id].state if track_id in self.tracks else MONITORING

    def status_text(self, track_id, t):
        """Short label for the video overlay, e.g. 'FALL? down 2s/3s', or None when nothing to show."""
        tr = self.tracks.get(track_id)
        if tr is None or tr.state == MONITORING:
            return None
        if tr.state == ALERTED:
            return "ALERT SENT"
        down = t - tr.lying_since if tr.lying_since is not None else 0
        label = "FALL?" if tr.fast_drop else "DOWN"
        return f"{label} {down:.0f}s/{self._alert_after(tr):.0f}s"

    def update(self, track_id, t, xy, conf=None):
        """Feed one person's keypoints for one frame. Returns an alert dict once per incident, else None."""
        tr = self.tracks.setdefault(track_id, Track())
        tr.last_seen = t
        s = measure(t, xy, conf)
        if tr.state == DOWN_PENDING:
            tr.frames_while_down += 1
            tr.hidden_frames_while_down += s is None
        if s is None:
            return None  # visibility uncertain: hold state

        tr.history.append(s)
        while tr.history and t - tr.history[0].t > config.HISTORY_SECONDS:
            tr.history.popleft()

        lying = s.angle_deg >= config.LYING_ANGLE_DEG
        if not lying:
            # Torso length shrinks when lying (foreshortening), so only learn it while upright
            tr.upright_torso_len = s.torso_len if tr.upright_torso_len is None else (
                0.9 * tr.upright_torso_len + 0.1 * s.torso_len)
        tr.lying_since = (tr.lying_since or t) if lying else None
        tr.upright_since = None if lying else (tr.upright_since or t)
        recovered = tr.upright_since is not None and t - tr.upright_since >= config.RECOVER_SECONDS

        if tr.state == MONITORING:
            if lying:
                tr.state = DOWN_PENDING
                tr.fast_drop = self._fast_drop(tr, t)
                tr.frames_while_down = tr.hidden_frames_while_down = 0
        elif tr.state == DOWN_PENDING:
            if recovered:
                tr.state = MONITORING
            elif tr.lying_since is not None and t - tr.lying_since >= self._alert_after(tr):
                tr.state = ALERTED
                return self._build_alert(track_id, tr, s, t)
        elif tr.state == ALERTED and recovered:
            tr.state = MONITORING
        return None

    def _alert_after(self, tr):
        return config.FALL_ALERT_SECONDS if tr.fast_drop else config.DOWN_ALERT_SECONDS

    def _fast_drop(self, tr, t):
        """If the hips dropped fast just now, return {'torsos', 'seconds'}, else None."""
        scale = tr.upright_torso_len
        if scale is None:
            return None
        window = [h for h in tr.history if t - h.t <= config.DROP_WINDOW_SECONDS]
        if len(window) < 2:
            return None
        top = min(window, key=lambda h: h.hip[1])  # image y grows downward
        drop = (window[-1].hip[1] - top.hip[1]) / scale
        if drop < config.DROP_MIN_TORSOS:
            return None
        return {"torsos": round(drop, 1), "seconds": round(max(window[-1].t - top.t, 0.1), 1)}

    def _movement(self, tr, t):
        """(speed, seconds measured): average speed of hips and shoulders since the person settled on the ground, in torso lengths per second.

        Positions are averaged in 0.5 s bins first, so keypoint jitter doesn't look like movement.
        """
        start = max(t - config.MOVEMENT_WINDOW_SECONDS, tr.lying_since + 0.5)  # skip the fall itself
        window = [h for h in tr.history if h.t >= start]
        if len(window) < 2:
            return None
        bins = {}
        for h in window:
            bins.setdefault(int((h.t - start) / 0.5), []).append(np.concatenate([h.hip, h.shoulder]))
        points = [np.mean(v, axis=0) for _, v in sorted(bins.items())]
        if len(points) < 2:
            return None
        path = sum(np.linalg.norm(b[:2] - a[:2]) + np.linalg.norm(b[2:] - a[2:])
                   for a, b in zip(points, points[1:])) / 2
        scale = tr.upright_torso_len or window[-1].torso_len
        seconds = window[-1].t - window[0].t
        return path / scale / seconds, seconds

    def _build_alert(self, track_id, tr, s, t):
        down_for = t - tr.lying_since
        movement, moved_over = self._movement(tr, t) or (None, 0)
        hidden = tr.hidden_frames_while_down / max(tr.frames_while_down, 1)

        reasons = []
        if tr.fast_drop:
            reasons.append(f"Went down fast: hips dropped {tr.fast_drop['torsos']} body-lengths "
                           f"in {tr.fast_drop['seconds']}s")
        else:
            reasons.append("Went down slowly (no sudden drop), like slumping or sliding down")
        reasons.append(f"Lying down for {down_for:.0f}s (torso {s.angle_deg:.0f}° from upright)")
        if movement is not None:
            if movement < config.LOW_MOVEMENT_TORSOS_PER_SEC:
                reasons.append(f"Very little movement in the last {moved_over:.0f}s")
            else:
                reasons.append("Still moving")
        if hidden > 0.3:
            reasons.append(f"Body partly hidden {hidden:.0%} of the time, so less certain")

        fast = tr.fast_drop is not None
        return {
            "type": "possible_fall" if fast else "person_down",
            "urgency": "high" if fast else "medium",
            "summary": "Possible fall, person not getting up" if fast else "Person down and not getting up",
            "reasons": reasons,
            "track_id": track_id,
            "metrics": {
                "down_seconds": round(down_for, 1),
                "torso_angle_deg": round(s.angle_deg),
                "drop_torsos": tr.fast_drop["torsos"] if fast else None,
                "movement_torsos_per_sec": None if movement is None else round(movement, 2),
                "hidden_fraction": round(hidden, 2),
            },
        }

    def forget_stale(self, t):
        for tid in [k for k, v in self.tracks.items() if t - v.last_seen > config.FORGET_TRACK_SECONDS]:
            del self.tracks[tid]
