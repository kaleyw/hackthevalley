"""Fall-like sequence detection over pose keypoints, one state machine per tracked person.

States: MONITORING -> POSSIBLE_FALL -> ALERTED
- MONITORING -> POSSIBLE_FALL: hips drop fast AND the torso ends up near horizontal
- POSSIBLE_FALL -> ALERTED: the person stays lying for PERSIST_SECONDS (emits one alert)
- POSSIBLE_FALL / ALERTED -> MONITORING: the person is upright for RECOVER_SECONDS

Frames where the hips/shoulders aren't visible are "uncertain": they never count
as lying or as upright, so the state just holds.
"""

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

import config

# COCO keypoint indices used by YOLO pose
L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 5, 6, 11, 12

MONITORING = "monitoring"
POSSIBLE_FALL = "possible_fall"
ALERTED = "alerted"


@dataclass
class Sample:
    t: float
    hip_y: float
    torso_len: float
    angle_deg: float  # torso angle from vertical: 0 = upright, 90 = horizontal


@dataclass
class Track:
    state: str = MONITORING
    history: deque = field(default_factory=deque)
    lying_since: float | None = None
    upright_since: float | None = None
    last_seen: float = 0.0
    upright_torso_len: float | None = None  # body-size reference, measured while upright


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
    return Sample(t=t, hip_y=float(hip[1]), torso_len=torso_len, angle_deg=angle)


class FallDetector:
    def __init__(self):
        self.tracks: dict[int, Track] = {}

    def state(self, track_id):
        return self.tracks[track_id].state if track_id in self.tracks else MONITORING

    def update(self, track_id, t, xy, conf=None):
        """Feed one person's keypoints for one frame. Returns an alert dict once per fall, else None."""
        tr = self.tracks.setdefault(track_id, Track())
        tr.last_seen = t
        s = measure(t, xy, conf)
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
            if lying and self._dropped_fast(tr, t):
                tr.state = POSSIBLE_FALL
        elif tr.state == POSSIBLE_FALL:
            if recovered:
                tr.state = MONITORING
            elif tr.lying_since is not None and t - tr.lying_since >= config.PERSIST_SECONDS:
                tr.state = ALERTED
                return {
                    "track_id": track_id,
                    "lying_seconds": round(t - tr.lying_since, 1),
                    "torso_angle_deg": round(s.angle_deg),
                }
        elif tr.state == ALERTED and recovered:
            tr.state = MONITORING
        return None

    def _dropped_fast(self, tr, t):
        scale = tr.upright_torso_len
        if scale is None:
            return False
        window = [h for h in tr.history if t - h.t <= config.DROP_WINDOW_SECONDS]
        if len(window) < 2:
            return False
        drop = window[-1].hip_y - min(h.hip_y for h in window)  # image y grows downward
        return drop / scale >= config.DROP_MIN_TORSOS

    def forget_stale(self, t):
        for tid in [k for k, v in self.tracks.items() if t - v.last_seen > config.FORGET_TRACK_SECONDS]:
            del self.tracks[tid]
