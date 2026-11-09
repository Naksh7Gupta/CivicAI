"""Video receiver with optional absolute frame timestamps for GPS synchronization."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2


class StreamReceiver:
    def __init__(self, source=0, recording_start_time=None):
        self.source = source
        self.capture = None
        self.recording_start_time = self._parse_start_time(recording_start_time)
        self.is_file_source = isinstance(source, (str, Path)) and Path(source).is_file()

    @staticmethod
    def _parse_start_time(value):
        if value is None or value == "":
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recording_start_time must include a timezone offset")
        return value.astimezone(timezone.utc)

    def start(self):
        self.capture = cv2.VideoCapture(self.source)
        if not self.capture.isOpened():
            raise RuntimeError("Unable to open video stream")

    def read_with_timestamp(self):
        if self.capture is None:
            return None, None
        media_position_ms = self.capture.get(cv2.CAP_PROP_POS_MSEC) if self.is_file_source else None
        success, frame = self.capture.read()
        if not success:
            return None, None
        if self.is_file_source:
            if self.recording_start_time is None:
                return frame, None
            return frame, self.recording_start_time + timedelta(milliseconds=media_position_ms or 0.0)
        return frame, datetime.now(timezone.utc)

    def read(self):
        frame, _ = self.read_with_timestamp()
        return frame

    def release(self):
        if self.capture:
            self.capture.release()
            self.capture = None
