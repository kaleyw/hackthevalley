"""Run YOLO Pose + ByteTrack on a video or webcam, detect people who go down and stay down,
send alerts to the backend, and confirm when someone reaches them.

Examples:
    python vision/run.py                          # webcam
    python vision/run.py --source data/tune/fall-01.mp4
    python vision/run.py --source data/tune/fall-01.mp4 --device cpu --no-show
"""

import argparse
import csv
import threading
import time
from datetime import datetime, timedelta, timezone

import cv2
import requests
from ultralytics import YOLO

import config
from detector import ALERTED, DOWN_PENDING, MONITORING, FallDetector
from help_watch import HelpWatcher

STATE_COLORS = {DOWN_PENDING: (0, 165, 255), ALERTED: (0, 0, 255)}  # BGR
HELP_COLOR = (0, 200, 0)


def send_event(alert):
    """POST an alert to the backend. Returns the event ID, or None if the backend is unreachable."""
    now = datetime.now(timezone.utc)
    event = {
        "camera_id": config.CAMERA_ID,
        "location": config.CAMERA_LOCATION,
        "detected_at": now.isoformat(),
        "went_down_at": (now - timedelta(seconds=alert["metrics"]["down_seconds"])).isoformat(),
        **alert,
    }
    try:
        r = requests.post(f"{config.BACKEND_URL}/events", json=event, timeout=2)
        r.raise_for_status()
        print(f"[event] sent {alert['type']}: {r.json()} | " + "; ".join(alert["reasons"]))
        return r.json()["id"]
    except Exception as e:  # never let a failed send stop the camera
        print(f"[event] couldn't send alert to the backend: {e}")
        return None


def send_help_detected(event_id):
    try:
        requests.post(f"{config.BACKEND_URL}/events/{event_id}/help-detected", timeout=2).raise_for_status()
        print(f"[event] camera confirmed someone is with the person (event {event_id})")
    except requests.RequestException as e:
        print(f"[event] couldn't report help for event {event_id}: {e}")


def heartbeat_loop(stop):
    """Tell the backend this camera is alive, so the dashboard can warn when it isn't."""
    while not stop.wait(config.HEARTBEAT_SECONDS):
        try:
            requests.post(f"{config.BACKEND_URL}/cameras/{config.CAMERA_ID}/heartbeat",
                          json={"location": config.CAMERA_LOCATION}, timeout=1)
        except requests.RequestException:
            pass  # backend down; the dashboard will show the camera as offline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="0", help="webcam index or video path")
    ap.add_argument("--device", default=config.DEVICE)
    ap.add_argument("--model", default=config.MODEL)
    ap.add_argument("--no-show", action="store_true", help="don't open a preview window")
    ap.add_argument("--debug", action="store_true", help="show detector measurements on the video")
    args = ap.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source
    # Use video time for files so timings don't depend on how fast we process frames
    fps = None if isinstance(source, int) else (cv2.VideoCapture(source).get(cv2.CAP_PROP_FPS) or 30)

    model = YOLO(args.model)
    detector = FallDetector()
    helpers = HelpWatcher()
    stop = threading.Event()
    threading.Thread(target=heartbeat_loop, args=(stop,), daemon=True).start()
    start = time.monotonic()
    last_state = {}

    # Every run writes a per-frame log for tuning thresholds (data/ is not committed)
    log_dir = config.ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run-{datetime.now():%Y%m%d-%H%M%S}.csv"
    log_file = open(log_path, "w", newline="")
    log = csv.writer(log_file)
    log.writerow(["t", "track_id", "state", "torso_angle", "box_ratio", "torso_conf"])
    print(f"[camera] running. Logging to {log_path}. Press q in the video window to stop.")

    results = model.track(source=source, device=args.device, tracker=config.TRACKER,
                          persist=True, stream=True, verbose=False)
    try:
        for i, r in enumerate(results):
            t = i / fps if fps else time.monotonic() - start
            frame = r.plot()
            boxes = {}

            if r.boxes is not None and r.boxes.id is not None and r.keypoints is not None:
                ids = r.boxes.id.int().tolist()
                xyxy = r.boxes.xyxy.cpu().numpy()
                xy = r.keypoints.xy.cpu().numpy()
                conf = r.keypoints.conf.cpu().numpy() if r.keypoints.conf is not None else None
                boxes = dict(zip(ids, xyxy))
                frame_h, frame_w = r.orig_shape
                m = config.EDGE_MARGIN_PX
                for j, tid in enumerate(ids):
                    x1, y1, x2, y2 = xyxy[j]
                    # A person cut off by the frame edge can look wide while standing, so only
                    # give the detector the box when the whole body is visible
                    in_frame = x1 > m and y1 > m and x2 < frame_w - m and y2 < frame_h - m
                    alert = detector.update(tid, t, xy[j], None if conf is None else conf[j],
                                            xyxy[j] if in_frame else None)
                    if alert and (event_id := send_event(alert)) is not None:
                        helpers.watch(tid, event_id, xyxy[j], t)

                    state = detector.state(tid)
                    if state != last_state.get(tid, MONITORING):
                        tr = detector.tracks[tid]
                        how = "fast" if tr.fast_drop else "slowly"
                        why = "body shape" if tr.lying_by_box else "torso angle"
                        msg = {DOWN_PENDING: f"went down {how} (by {why}); alert if still down after "
                                             f"{detector._alert_after(tr):.0f}s",
                               ALERTED: "alert sent to dashboard", MONITORING: "back up; cancelled"}[state]
                        print(f"[#{tid}] {msg}")
                    last_state[tid] = state
                    d = detector.tracks[tid].debug
                    log.writerow([round(t, 2), tid, state, d.get("angle"), d.get("box_ratio"), d.get("conf")])

                    x1, y1, _, y2 = xyxy[j].astype(int)
                    if args.debug:
                        cv2.putText(frame, detector.debug_text(tid), (x1, min(y2 + 22, frame.shape[0] - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
                    label = detector.status_text(tid, t)
                    if label:
                        color = STATE_COLORS[detector.state(tid)]
                        if helpers.helper_near(tid):
                            label, color = "SOMEONE WITH THEM", HELP_COLOR
                        cv2.putText(frame, f"#{tid} {label}", (x1, max(y1 - 30, 20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

            for event_id in helpers.update(boxes, t):
                send_help_detected(event_id)
            detector.forget_stale(t)

            if not args.no_show:
                cv2.imshow("collapse detection (q to quit)", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        stop.set()
        log_file.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
