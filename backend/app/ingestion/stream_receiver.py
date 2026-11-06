"""Video stream receiver with frame-relative timestamps for GPS synchronization."""
import math
import cv2


class StreamReceiver:
    def __init__(self, source):
        self.source = source
        self.capture = None
        self.last_timestamp_ms = None
        self.frame_index = -1
        self.fps = None

    def start(self):
        if not isinstance(self.source, (str, bytes)):
            raise TypeError("Video source must be a filesystem path.")
        self.capture = cv2.VideoCapture(self.source)
        if not self.capture.isOpened():
            raise RuntimeError("Unable to open video stream")
        fps = float(self.capture.get(cv2.CAP_PROP_FPS))
        self.fps = fps if math.isfinite(fps) and fps > 0 else None
        self.last_timestamp_ms = None
        self.frame_index = -1

    def read(self):
        if self.capture is None:
            return None
        success, frame = self.capture.read()
        if not success:
            return None

        self.frame_index += 1
        timestamp_ms = float(self.capture.get(cv2.CAP_PROP_POS_MSEC))
        if not math.isfinite(timestamp_ms) or timestamp_ms < 0:
            timestamp_ms = None
        if timestamp_ms is None or (
            self.last_timestamp_ms is not None
            and timestamp_ms <= self.last_timestamp_ms
        ):
            timestamp_ms = (
                self.frame_index * 1000.0 / self.fps if self.fps is not None else None
            )
        self.last_timestamp_ms = timestamp_ms
        return frame

    def release(self):
        if self.capture:
            self.capture.release()
            self.capture = None
