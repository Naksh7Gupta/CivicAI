"""Pothole detection."""
from ultralytics import YOLO

from app.core.config import (
    MODEL_PATH,
    CONFIDENCE_THRESHOLD
)


class PotholeDetector:

    def __init__(self, device="cpu"):

        self.device = device
        self.model = YOLO(str(MODEL_PATH))

    def detect(self, frame):

        results = self.model.track(

            frame,

            persist=True,

            tracker="bytetrack.yaml",

            conf=CONFIDENCE_THRESHOLD,

            device=self.device,

            verbose=False

        )

        return results[0]

    def detect_image(self, image):

        results = self.model.predict(
            image,
            conf=CONFIDENCE_THRESHOLD,
            device=self.device,
            verbose=False
        )

        return results[0]