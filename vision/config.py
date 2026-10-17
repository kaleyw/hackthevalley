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

# Fall detection (distances are in torso lengths, so they don't depend on how
# close the person is to the camera)
HISTORY_SECONDS = 3.0      # how much keypoint history to keep per person
DROP_WINDOW_SECONDS = 0.6  # look back this far when measuring a drop
DROP_MIN_TORSOS = 0.8      # hips must drop at least this many torso lengths in the window
LYING_ANGLE_DEG = 60       # torso angle from vertical that counts as "lying"
PERSIST_SECONDS = 3.0      # must stay down this long before we alert
RECOVER_SECONDS = 2.0      # upright this long cancels a possible fall or re-arms after an alert
FORGET_TRACK_SECONDS = 10  # drop state for people we haven't seen in this long
