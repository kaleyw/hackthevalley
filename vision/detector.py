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
    lying_by_box: bool = False  # last "lying" decision came from body shape, not torso angle
    box: np.ndarray | None = None  # last bounding box, used to recognise the person after an ID change
    debug: dict = field(default_factory=dict)  # latest measurements, for the debug overlay and log


def iou(a, b):
    """Overlap of two (x1, y1, x2, y2) boxes: 0 = none, 1 = identical."""
    ix = max(0.0, float(min(a[2], b[2]) - max(a[0], b[0])))
    iy = max(0.0, float(min(a[3], b[3]) - max(a[1], b[1])))
    inter = ix * iy
    union = float((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1])) - inter
    return inter / union if union > 0 else 0.0


def box_ratio(box):
    """Width / height of a bounding box. A person lying flat is usually wider than tall."""
    if box is None:
        return None
    w, h = float(box[2] - box[0]), float(box[3] - box[1])
    return w / h if h > 0 else None


def measure(t, xy, conf):
    """Return a Sample, or None if the torso keypoints aren't visible enough."""
    idx = [L_SHOULDER, R_SHOULDER, L_HIP, R_HIP]
    if conf is not None and np.min(conf[idx]) < config.KEYPOINT_MIN_CONF:
        return None
    shoulder = (xy[L_SHOULDER] + xy[R_SHOULDER]) / 2
    hip = (xy[L_HIP] + xy[R_HIP]) / 2
    dx, dy = shoulder - hip
    torso_len = math.hypot(float(dx), float(dy))
    if torso_len < 1:
        return None
    angle = math.degrees(math.atan2(abs(float(dx)), abs(float(dy))))
    return Sample(t=t, hip=hip, shoulder=shoulder, torso_len=torso_len, angle_deg=angle)


class FallDetector:
    def __init__(self):
        self.tracks: dict[int, Track] = {}
        self.handoffs: list[tuple[int, int]] = []  # (old ID, new ID) since last pop_handoffs()
        self.got_up: list[int] = []  # track IDs that got up after an alert, since last pop_got_up()

    def pop_got_up(self):
        got_up, self.got_up = self.got_up, []
        return got_up

    def pop_handoffs(self):
        handoffs, self.handoffs = self.handoffs, []
        return handoffs

    def _find_handoff(self, t, box):
        """A down person the tracker just lost, whose last box overlaps this new track's box."""
        best, best_iou = None, config.HANDOFF_IOU
        for tid, tr in self.tracks.items():
            if (tr.state != MONITORING and tr.box is not None and tr.last_seen < t
                    and t - tr.last_seen <= config.HANDOFF_SECONDS):
                overlap = iou(box, tr.box)
                if overlap >= best_iou:
                    best, best_iou = tid, overlap
        return best

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

    def update(self, track_id, t, xy, conf=None, box=None, box_in_frame=True):
        """Feed one person's keypoints (and bounding box) for one frame.

        Returns an alert dict once per incident, else None. "Lying" means the torso is near
        horizontal, or the torso is visibly tilted and the body's box is clearly wider than
        tall (covers camera angles that make a lying torso look less tilted than it is).
        The box rule is skipped when box_in_frame is False (a person cut off by the frame edge
        can look wide while standing).

        When someone walks past, the tracker sometimes gives the person on the ground a new
        ID; a new ID that appears where a down person was just lost takes over their state.
        """
        if track_id not in self.tracks and box is not None:
            old_id = self._find_handoff(t, box)
            if old_id is not None:
                self.tracks[track_id] = self.tracks.pop(old_id)
                self.handoffs.append((old_id, track_id))
        tr = self.tracks.setdefault(track_id, Track())
        tr.last_seen = t
        if box is not None:
            tr.box = box
        s = measure(t, xy, conf)
        ratio = box_ratio(box) if box_in_frame else None
        torso_lying = s is not None and s.angle_deg >= config.LYING_ANGLE_DEG
        # Body shape only counts when we can see the torso and it's tilted; a wide box alone
        # (a face close to the camera, someone sitting nearby) is not evidence of lying down
        box_lying = (s is not None and ratio is not None and ratio >= config.LYING_BOX_RATIO
                     and s.angle_deg >= config.BOX_RULE_MIN_ANGLE_DEG)
        conf_min = None if conf is None else float(np.min(conf[[L_SHOULDER, R_SHOULDER, L_HIP, R_HIP]]))
        tr.debug = {"angle": None if s is None else round(s.angle_deg), "box_ratio": None if ratio is None else round(ratio, 2),
                    "conf": None if conf_min is None else round(conf_min, 2)}

        if tr.state == DOWN_PENDING:
            tr.frames_while_down += 1
            tr.hidden_frames_while_down += s is None
        if s is None:
            return None  # visibility uncertain: hold state

        tr.history.append(s)
        while tr.history and t - tr.history[0].t > config.HISTORY_SECONDS:
            tr.history.popleft()

        lying = torso_lying or box_lying
        if lying:
            tr.lying_by_box = not torso_lying
        else:
            # Torso length shrinks when lying (foreshortening), so only learn it while upright
            tr.upright_torso_len = s.torso_len if tr.upright_torso_len is None else (
                0.9 * tr.upright_torso_len + 0.1 * s.torso_len)
        if lying:
            tr.lying_since = tr.lying_since or t
        tr.upright_since = None if lying else (tr.upright_since or t)
        recovered = tr.upright_since is not None and t - tr.upright_since >= config.RECOVER_SECONDS
        if recovered:
            # Only a real recovery restarts the countdown; a glitchy frame (someone walking
            # past) doesn't
            tr.lying_since = None

        if tr.state == MONITORING:
            if lying:
                tr.state = DOWN_PENDING
                tr.fast_drop = self._fast_drop(tr, t)
                tr.frames_while_down = tr.hidden_frames_while_down = 0
        elif tr.state == DOWN_PENDING:
            if recovered:
                tr.state = MONITORING
            elif (tr.lying_since is not None and t - tr.lying_since >= self._alert_after(tr)
                  and self._visible_fraction(tr) >= config.MIN_VISIBLE_WHILE_DOWN):
                tr.state = ALERTED
                return self._build_alert(track_id, tr, s, t, ratio)
        elif tr.state == ALERTED and recovered:
            tr.state = MONITORING
            self.got_up.append(track_id)  # the alert stays open for staff; bystanders get an update
        return None

    def debug_text(self, track_id):
        """Detector measurements for the --debug overlay, e.g. 'torso 72deg  box 1.6  conf 0.81'."""
        d = self.tracks[track_id].debug if track_id in self.tracks else {}
        fmt = lambda v, suffix="": "-" if v is None else f"{v}{suffix}"
        return f"torso {fmt(d.get('angle'), 'deg')}  box {fmt(d.get('box_ratio'))}  conf {fmt(d.get('conf'))}"

    def _visible_fraction(self, tr):
        return 1 - tr.hidden_frames_while_down / max(tr.frames_while_down, 1)

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
        drop = float(window[-1].hip[1] - top.hip[1]) / scale
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
        return float(path / scale / seconds), seconds

    def _build_alert(self, track_id, tr, s, t, ratio):
        down_for = t - tr.lying_since
        movement, moved_over = self._movement(tr, t) or (None, 0)
        hidden = tr.hidden_frames_while_down / max(tr.frames_while_down, 1)

        reasons = []
        if tr.fast_drop:
            reasons.append(f"Went down fast: hips dropped {tr.fast_drop['torsos']} body-lengths "
                           f"in {tr.fast_drop['seconds']}s")
        else:
            reasons.append("Went down slowly (no sudden drop), like slumping or sliding down")
        if tr.lying_by_box and ratio is not None:
            reasons.append(f"Lying flat for {down_for:.0f}s (body {ratio:.1f}x wider than tall)")
        else:
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
                "box_ratio": None if ratio is None else round(ratio, 2),
                "drop_torsos": tr.fast_drop["torsos"] if fast else None,
                "movement_torsos_per_sec": None if movement is None else round(movement, 2),
                "hidden_fraction": round(hidden, 2),
            },
        }

    def forget_stale(self, t):
        for tid in [k for k, v in self.tracks.items() if t - v.last_seen > config.FORGET_TRACK_SECONDS]:
            del self.tracks[tid]
