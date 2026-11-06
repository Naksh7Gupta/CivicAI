"""Road segmentation and mask-derived region of interest."""
from dataclasses import dataclass
import logging
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from app.core.config import (
    ROI_MIN_AREA_RATIO,
    ROI_MIN_HEIGHT,
    ROI_MIN_WIDTH,
    ROI_PADDING_RATIO,
    ROAD_SEGMENTATION_CLASS_ID,
    ROAD_SEGMENTATION_MODEL_PATH,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoadROI:
    image: np.ndarray
    bounds: tuple[int, int, int, int]
    mask: np.ndarray
    used_fallback: bool


class RoadROIProcessor:
    """Create a padded road crop and retain its coordinates in the source frame."""

    def __init__(self, device="cpu"):
        self.device = device
        self.model = None
        model_path = Path(ROAD_SEGMENTATION_MODEL_PATH)
        if model_path.exists():
            self.model = YOLO(str(model_path))
        else:
            logger.warning(
                "Road segmentation model is unavailable at %s; "
                "full-frame detection will be used.",
                model_path,
            )

    def process(self, frame: np.ndarray) -> RoadROI:
        height, width = frame.shape[:2]
        full_bounds = (0, 0, width, height)
        full_mask = np.ones((height, width), dtype=np.uint8)

        if self.model is None:
            return RoadROI(frame, full_bounds, full_mask, True)

        results = self.model.predict(
            frame,
            device=self.device,
            classes=[ROAD_SEGMENTATION_CLASS_ID],
            verbose=False,
        )
        masks = results[0].masks
        if masks is None or masks.data is None:
            return RoadROI(frame, full_bounds, full_mask, True)

        mask = masks.data.max(dim=0).values.cpu().numpy()
        mask = cv2.resize(mask, (width, height), interpolation=cv2.INTER_NEAREST)
        binary_mask = (mask > 0.5).astype(np.uint8)
        area_ratio = float(binary_mask.mean())
        ys, xs = np.where(binary_mask > 0)

        if (
            not len(xs)
            or area_ratio < ROI_MIN_AREA_RATIO
            or xs.max() - xs.min() + 1 < ROI_MIN_WIDTH
            or ys.max() - ys.min() + 1 < ROI_MIN_HEIGHT
        ):
            return RoadROI(frame, full_bounds, full_mask, True)

        padding_x = int((xs.max() - xs.min() + 1) * ROI_PADDING_RATIO)
        padding_y = int((ys.max() - ys.min() + 1) * ROI_PADDING_RATIO)
        x1 = max(0, int(xs.min()) - padding_x)
        y1 = max(0, int(ys.min()) - padding_y)
        x2 = min(width, int(xs.max()) + padding_x + 1)
        y2 = min(height, int(ys.max()) + padding_y + 1)

        crop = frame[y1:y2, x1:x2].copy()
        crop_mask = binary_mask[y1:y2, x1:x2]
        crop[crop_mask == 0] = 0
        return RoadROI(crop, (x1, y1, x2, y2), binary_mask, False)

    @staticmethod
    def annotate(frame: np.ndarray, roi: RoadROI, result) -> np.ndarray:
        annotated = frame.copy()
        if not roi.used_fallback:
            overlay = annotated.copy()
            overlay[roi.mask > 0] = (
                0.7 * overlay[roi.mask > 0] + np.array([0, 100, 0])
            ).astype(np.uint8)
            annotated = cv2.addWeighted(annotated, 0.7, overlay, 0.3, 0)

        plotted = result.plot()
        x1, y1, x2, y2 = roi.bounds
        if (x2 - x1, y2 - y1) == plotted.shape[1::-1]:
            annotated[y1:y2, x1:x2] = plotted
        return annotated