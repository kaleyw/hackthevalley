"""Run YOLO Pose + ByteTrack on a video or webcam, detect fall-like sequences, and send events to the backend.

Examples:
    python vision/run.py                          # webcam
    python vision/run.py --source data/tune/fall-01.mp4
    python vision/run.py --source data/tune/fall-01.mp4 --device cpu --no-show
"""

import argparse
import time
from datetime import datetime, timezone

import cv2
import requests
from ultralytics import YOLO

import config
from detector import ALERTED, POSSIBLE_FALL, FallDetector

STATE_COLORS = {POSSIBLE_FALL: (0, 165, 255), ALERTED: (0, 0, 255)}  # BGR


def send_event(alert):
    event = {
        "camera_id": config.CAMERA_ID,
        "location": config.CAMERA_LOCATION,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "type": "possible_fall",
        **alert,
    }
    try:
        r = requests.post(f"{config.BACKEND_URL}/events", json=event, timeout=2)
        r.raise_for_status()
        print(f"[event] sent: {r.json()}")
    except requests.RequestException as e:
        print(f"[event] backend unreachable, event not sent: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="0", help="webcam index or video path")
    ap.add_argument("--device", default=config.DEVICE)
    ap.add_argument("--model", default=config.MODEL)
    ap.add_argument("--no-show", action="store_true", help="don't open a preview window")
    args = ap.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source
    # Use video time for files so timings don't depend on how fast we process frames
    fps = None if isinstance(source, int) else (cv2.VideoCapture(source).get(cv2.CAP_PROP_FPS) or 30)

    model = YOLO(args.model)
    detector = FallDetector()
    start = time.monotonic()

    results = model.track(source=source, device=args.device, tracker=config.TRACKER,
                          persist=True, stream=True, verbose=False)
    for i, r in enumerate(results):
        t = i / fps if fps else time.monotonic() - start
        frame = r.plot()

        if r.boxes is not None and r.boxes.id is not None and r.keypoints is not None:
            ids = r.boxes.id.int().tolist()
            boxes = r.boxes.xyxy.cpu().numpy()
            xy = r.keypoints.xy.cpu().numpy()
            conf = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else None
            for j, tid in enumerate(ids):
                alert = detector.update(tid, t, xy[j], None if conf is None else conf[j])
                if alert:
                    send_event(alert)
                state = detector.state(tid)
                if state in STATE_COLORS:
                    x1, y1 = boxes[j][:2].astype(int)
                    cv2.putText(frame, f"#{tid} {state.upper()}", (x1, max(y1 - 30, 20)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, STATE_COLORS[state], 2)
        detector.forget_stale(t)

        if not args.no_show:
            cv2.imshow("fall detection (q to quit)", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
