"""Camera-confirmed help: after an alert, watch for someone staying next to the person.

This is how we verify help actually reached them without relying on anyone tapping a button.
"""

from dataclasses import dataclass

import numpy as np

import config
from detector import iou


@dataclass
class Watch:
    event_id: int
    box: np.ndarray       # last known box (x1, y1, x2, y2) of the person who went down
    box_seen_at: float
    near_since: float | None = None
    last_near_at: float | None = None


class HelpWatcher:
    def __init__(self):
        self.watches: dict[int, Watch] = {}  # track ID of the person who went down -> watch

    def watch(self, track_id, event_id, box, t):
        self.watches[track_id] = Watch(event_id, box, t)

    def rename(self, old_id, new_id):
        """The tracker gave the person on the ground a new ID."""
        if old_id in self.watches:
            self.watches[new_id] = self.watches.pop(old_id)

    def update(self, boxes, t):
        """boxes: {track_id: xyxy} for this frame. Returns event IDs where help was just confirmed."""
        confirmed = []
        for tid, w in list(self.watches.items()):
            if tid in boxes:
                w.box, w.box_seen_at = boxes[tid], t
            elif t - w.box_seen_at > config.HELP_KEEP_LAST_POSITION_SECONDS:
                del self.watches[tid]  # lost track of the person; stop watching
                continue

            center = (w.box[:2] + w.box[2:]) / 2
            radius = config.HELP_RADIUS_BOXES * max(w.box[2] - w.box[0], w.box[3] - w.box[1])
            # A box mostly overlapping the person is a duplicate detection of them, not a helper
            someone_near = any(np.linalg.norm((b[:2] + b[2:]) / 2 - center) <= radius
                               and iou(b, w.box) < config.SAME_PERSON_IOU
                               for other, b in boxes.items() if other != tid)
            if someone_near:
                w.last_near_at = t
                w.near_since = w.near_since or t
            elif w.last_near_at is None or t - w.last_near_at > config.HELP_GAP_TOLERANCE_SECONDS:
                w.near_since = None  # they left (e.g. just walked past): restart the count
            if w.near_since is not None and t - w.near_since >= config.HELP_CONFIRM_SECONDS:
                confirmed.append(w.event_id)
                del self.watches[tid]
        return confirmed

    def helper_near(self, track_id):
        w = self.watches.get(track_id)
        return w is not None and w.near_since is not None
