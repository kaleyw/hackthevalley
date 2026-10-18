"""Live camera preview for the dashboard: serves the annotated frames as an MJPEG stream.

The server only listens on this computer (127.0.0.1). The dashboard's dev server forwards
/camera/stream.mjpg to it, so the browser never talks to this port directly.
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

MAX_WIDTH = 960
JPEG_QUALITY = 70
MAX_FPS = 15


class FrameHub:
    """Holds the newest JPEG so every viewer gets the latest frame without slowing detection."""

    def __init__(self):
        self.cond = threading.Condition()
        self.jpeg = None
        self.count = 0
        self._last = 0.0

    def update(self, frame):
        now = time.monotonic()
        if now - self._last < 1 / MAX_FPS:
            return
        self._last = now
        h, w = frame.shape[:2]
        if w > MAX_WIDTH:
            frame = cv2.resize(frame, (MAX_WIDTH, int(h * MAX_WIDTH / w)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            return
        with self.cond:
            self.jpeg = buf.tobytes()
            self.count += 1
            self.cond.notify_all()

    def wait_next(self, last_count, timeout=5.0):
        with self.cond:
            self.cond.wait_for(lambda: self.count != last_count, timeout)
            return self.jpeg, self.count


def serve(hub, port):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] == "/snapshot.jpg":
                jpeg, _ = hub.wait_next(-1, timeout=2)
                if jpeg is None:
                    self.send_error(503, "No frame yet")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(jpeg)
                return
            if self.path.split("?")[0] != "/stream.mjpg":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            count = -1
            try:
                while True:
                    jpeg, count = hub.wait_next(count)
                    if jpeg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # viewer closed the tab

        def log_message(self, *args):
            pass  # keep the detection console readable

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
