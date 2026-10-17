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
CAMERA_LOCATION = os.getenv("CAMERA_LOCATION", "Demo venue - Room A")
CAMERA_ID = "cam-1"

# Keypoints below this confidence count as "not visible"
KEYPOINT_MIN_CONF = 0.4

# Detection (distances are in torso lengths, so they don't depend on how close
# the person is to the camera)
HISTORY_SECONDS = 6.0      # how much keypoint history to keep per person
DROP_WINDOW_SECONDS = 0.6  # look back this far when measuring a drop
DROP_MIN_TORSOS = 0.8      # hips must drop at least this many torso lengths in the window
LYING_ANGLE_DEG = 60       # torso angle from vertical that counts as "lying"
FALL_ALERT_SECONDS = 3.0   # fast fall: alert after staying down this long (high urgency)
DOWN_ALERT_SECONDS = 12.0  # slow collapse / lying down: alert after staying down this long
RECOVER_SECONDS = 2.0      # upright this long cancels a pending alert or re-arms after one
FORGET_TRACK_SECONDS = 10  # drop state for people we haven't seen in this long

# Movement after going down (only used to explain alerts, never required to alert)
MOVEMENT_WINDOW_SECONDS = 5.0
LOW_MOVEMENT_TORSOS_PER_SEC = 0.15

# Camera-confirmed help: after an alert, someone staying this close to the person for
# this long counts as "someone is with them" (distance in multiples of the person's box size)
HELP_RADIUS_BOXES = 1.0
HELP_CONFIRM_SECONDS = 3.0
HELP_KEEP_LAST_POSITION_SECONDS = 10.0  # helpers often block the camera's view of the person

HEARTBEAT_SECONDS = 2.0  # how often the camera tells the backend it's alive
