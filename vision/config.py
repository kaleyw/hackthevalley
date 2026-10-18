"""All tunable settings for the vision pipeline in one place.

These thresholds are prototype values to tune on data/tune/ clips. They are not
medically validated.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Model and tracker
MODEL = "yolo11n-pose.pt"  # try yolo11s-pose.pt for better accuracy on distant people
TRACKER = str(Path(__file__).with_name("bytetrack.yaml"))
DEVICE = "mps"  # Apple Silicon GPU; use "cpu" if mps errors, or 0 for an NVIDIA GPU

# Where events go
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
CAMERA_LOCATION = os.getenv("CAMERA_LOCATION", "Union Station")
CAMERA_ID = "cam-1"

# Keypoints below this confidence count as "not visible" (pose models are less confident
# on people lying down, so this is kept low; the 12 s wait smooths out noisy frames)
KEYPOINT_MIN_CONF = 0.2

# Detection (distances are in torso lengths, so they don't depend on how close
# the person is to the camera)
HISTORY_SECONDS = 6.0      # how much keypoint history to keep per person
DROP_WINDOW_SECONDS = 0.6  # look back this far when measuring a drop
DROP_MIN_TORSOS = 0.8      # hips must drop at least this many torso lengths in the window
LYING_ANGLE_DEG = 60       # torso angle from vertical that counts as "lying"
LYING_BOX_RATIO = 1.3      # or: body box this many times wider than tall counts as "lying",
BOX_RULE_MIN_ANGLE_DEG = 35  # ...but only if the torso is visible and tilted at least this much
                             # (a face/shoulders close-up or someone sitting near the camera is wide too)
MIN_VISIBLE_WHILE_DOWN = 0.3  # don't alert unless the body was visible this much of the time down
EDGE_MARGIN_PX = 8         # the box rule only applies when the whole body is in frame (not cut off)
FALL_ALERT_SECONDS = 3.0   # fast fall: alert after staying down this long (high urgency)
DOWN_ALERT_SECONDS = 12.0  # slow collapse / lying down: alert after staying down this long
RECOVER_SECONDS = 2.0      # upright this long cancels a pending alert or re-arms after one
FORGET_TRACK_SECONDS = 10  # drop state for people we haven't seen in this long
HANDOFF_SECONDS = 3.0      # a new track ID appearing where a down person was lost this recently is them
HANDOFF_IOU = 0.3          # ...if its box overlaps their last box at least this much

# Movement after going down (only used to explain alerts, never required to alert)
MOVEMENT_WINDOW_SECONDS = 5.0
LOW_MOVEMENT_TORSOS_PER_SEC = 0.15

# Camera-confirmed help: after an alert, someone staying this close to the person for
# this long counts as "someone is with them" (distance in multiples of the person's box size)
HELP_RADIUS_BOXES = 1.0
HELP_CONFIRM_SECONDS = 10.0
HELP_GAP_TOLERANCE_SECONDS = 1.5  # a helper flickering out of detection this briefly doesn't restart the count
SAME_PERSON_IOU = 0.6  # a box overlapping the person this much is a duplicate detection of them, not a helper
HELP_KEEP_LAST_POSITION_SECONDS = 10.0  # helpers often block the camera's view of the person

HEARTBEAT_SECONDS = 2.0  # how often the camera tells the backend it's alive
