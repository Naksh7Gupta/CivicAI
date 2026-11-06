"""Video stream receiver with frame-timeline timestamps."""
import math
import cv2


class StreamReceiver:
    def __init__(self, source):
        self.source = source
        self.capture = None
        self.frame_index = 0
        self.fps = 0.0
        self.last_timestamp_ms = None

    def start(self):
        if not isinstance(self.source, (str, bytes)):
            raise TypeError("Video source must be a filesystem path.")
        self.capture = cv2.VideoCapture(self.source)
        if not self.capture.isOpened():
            raise RuntimeError("Unable to open video stream")
        self.fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 0.0)
        self.frame_index = 0
        self.last_timestamp_ms = None

    def read_with_timestamp(self):
        if self.capture is None:
            return None, None
        success, frame = self.capture.read()
        if not success:
            return None, None

        timestamp_ms = float(self.capture.get(cv2.CAP_PROP_POS_MSEC))
        valid_timestamp = math.isfinite(timestamp_ms) and timestamp_ms >= 0
        if self.frame_index > 0 and self.last_timestamp_ms is not None:
            valid_timestamp = valid_timestamp and timestamp_ms > self.last_timestamp_ms

        if not valid_timestamp:
            timestamp_ms = (
                self.frame_index * 1000.0 / self.fps
                if math.isfinite(self.fps) and self.fps > 0
                else None
            )

        if timestamp_ms is not None:
            self.last_timestamp_ms = timestamp_ms
        self.frame_index += 1
        return frame, timestamp_ms

    def read(self):
        frame, _ = self.read_with_timestamp()
        return frame

    def release(self):
        if self.capture:
            self.capture.release()
            self.capture = None
