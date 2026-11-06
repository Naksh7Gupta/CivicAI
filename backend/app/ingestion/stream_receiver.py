"""Video receiver with a monotonic media timestamp for each decoded frame."""
import math

import cv2


class StreamReceiver:
    def __init__(self, source):
        self.source = source
        self.capture = None
        self.fps = None
        self.frame_index = 0
        self.last_timestamp_seconds = None
        self.timestamp_source = None

    def start(self):
        if not isinstance(self.source, (str, bytes)):
            raise TypeError("Video source must be a filesystem path.")
        self.capture = cv2.VideoCapture(self.source)
        if not self.capture.isOpened():
            raise RuntimeError("Unable to open video stream")
        reported_fps = float(self.capture.get(cv2.CAP_PROP_FPS))
        self.fps = reported_fps if math.isfinite(reported_fps) and reported_fps > 0 else None

    def read(self):
        if self.capture is None:
            return None
        success, frame = self.capture.read()
        if not success:
            return None

        self.frame_index += 1
        reported_ms = float(self.capture.get(cv2.CAP_PROP_POS_MSEC))
        candidate = reported_ms / 1000.0
        if (
            math.isfinite(candidate)
            and candidate >= 0
            and (
                self.last_timestamp_seconds is None
                or candidate > self.last_timestamp_seconds
            )
        ):
            self.last_timestamp_seconds = candidate
            self.timestamp_source = "opencv_pos_msec"
        elif self.fps is not None:
            fallback = (self.frame_index - 1) / self.fps
            if (
                self.last_timestamp_seconds is None
                or fallback > self.last_timestamp_seconds
            ):
                self.last_timestamp_seconds = fallback
                self.timestamp_source = "frame_index_fps_fallback"
            else:
                self.last_timestamp_seconds = None
                self.timestamp_source = "unavailable"
        else:
            self.last_timestamp_seconds = None
            self.timestamp_source = "unavailable"
        return frame

    def release(self):
        if self.capture:
            self.capture.release()
            self.capture = None
