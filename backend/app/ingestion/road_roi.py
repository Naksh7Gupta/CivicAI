"""Road segmentation and mask-derived region of interest."""
from dataclasses import dataclass
import logging
from pathlib import Path

import cv2
import numpy as np
import torch

from app.core.config import (
    ROI_MIN_AREA_RATIO,
    ROI_MIN_HEIGHT,
    ROI_MIN_WIDTH,
    ROI_PADDING_RATIO,
    ROI_SEGMENTATION_INTERVAL,
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
        if ROI_SEGMENTATION_INTERVAL < 1:
            raise ValueError("ROI_SEGMENTATION_INTERVAL must be at least 1.")
        self.device = device
        self.model = None
        self.frame_index = 0
        self.cached_roi = None
        model_path = Path(ROAD_SEGMENTATION_MODEL_PATH)
        if model_path.exists():
            self.model = self._load_model(model_path)
        else:
            logger.warning(
                "Road segmentation model is unavailable at %s; "
                "full-frame detection will be used.",
                model_path,
            )

    @staticmethod
    def _install_mmcv_cpu_compatibility() -> None:
        """Provide optional MMCV operators unavailable in mmcv-lite."""
        import sys
        import types
        from torch.nn import functional as torch_functional

        if "mmcv.ops" in sys.modules:
            return

        ops = types.ModuleType("mmcv.ops")
        ops.point_sample = (
            lambda inputs, points, **kwargs: torch_functional.grid_sample(
                inputs,
                points * 2 - 1,
                align_corners=False,
            )
        )
        ops.sigmoid_focal_loss = (
            lambda *args, **kwargs: torch.tensor(0.0)
        )

        class UnusedOperator(torch.nn.Module):
            pass

        for name in (
            "CrissCrossAttention",
            "PSAMask",
            "DeformConv2d",
            "ModulatedDeformConv2d",
        ):
            setattr(ops, name, UnusedOperator)
        sys.modules["mmcv.ops"] = ops

    def _load_model(self, model_path: Path):
        self._install_mmcv_cpu_compatibility()
        from mmengine.config import Config
        from mmseg.apis import init_model

        checkpoint = torch.load(
            model_path,
            map_location="cpu",
            weights_only=False,
        )
        config = Config.fromstring(
            checkpoint["meta"]["config"],
            ".py",
        )
        config.model.test_cfg.mode = "whole"
        return init_model(
            config,
            str(model_path),
            device=str(self.device),
        )

    def process(self, frame: np.ndarray) -> RoadROI:
        self.frame_index += 1
        if (
            self.cached_roi is not None
            and (self.frame_index - 1) % ROI_SEGMENTATION_INTERVAL != 0
        ):
            return self._apply_cached_roi(frame, self.cached_roi)

        height, width = frame.shape[:2]
        full_bounds = (0, 0, width, height)
        full_mask = np.ones((height, width), dtype=np.uint8)

        if self.model is None:
            roi = RoadROI(frame, full_bounds, full_mask, True)
            self.cached_roi = roi
            return roi

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb_frame, (1024, 512))
        tensor = torch.from_numpy(resized).permute(2, 0, 1).float()
        mean = tensor.new_tensor(
            [123.675, 116.28, 103.53]
        )[:, None, None]
        std = tensor.new_tensor(
            [58.395, 57.12, 57.375]
        )[:, None, None]
        tensor = ((tensor - mean) / std).unsqueeze(0).to(
            self.device
        )
        metadata = [
            {
                "img_shape": resized.shape,
                "ori_shape": resized.shape,
                "pad_shape": resized.shape,
                "scale_factor": (1.0, 1.0, 1.0, 1.0),
            }
        ]
        with torch.no_grad():
            logits = self.model.inference(tensor, metadata)
        labels = logits.argmax(1)[0].cpu().numpy()
        binary_mask = cv2.resize(
            (labels == ROAD_SEGMENTATION_CLASS_ID).astype(np.uint8),
            (width, height),
            interpolation=cv2.INTER_NEAREST,
        )
        area_ratio = float(binary_mask.mean())
        ys, xs = np.where(binary_mask > 0)

        if (
            not len(xs)
            or area_ratio < ROI_MIN_AREA_RATIO
            or xs.max() - xs.min() + 1 < ROI_MIN_WIDTH
            or ys.max() - ys.min() + 1 < ROI_MIN_HEIGHT
        ):
            roi = RoadROI(frame, full_bounds, full_mask, True)
            self.cached_roi = roi
            return roi

        padding_x = int((xs.max() - xs.min() + 1) * ROI_PADDING_RATIO)
        padding_y = int((ys.max() - ys.min() + 1) * ROI_PADDING_RATIO)
        x1 = max(0, int(xs.min()) - padding_x)
        y1 = max(0, int(ys.min()) - padding_y)
        x2 = min(width, int(xs.max()) + padding_x + 1)
        y2 = min(height, int(ys.max()) + padding_y + 1)

        crop = frame[y1:y2, x1:x2].copy()
        crop_mask = binary_mask[y1:y2, x1:x2]
        crop[crop_mask == 0] = 0
        roi = RoadROI(crop, (x1, y1, x2, y2), binary_mask, False)
        self.cached_roi = roi
        return roi

    @staticmethod
    def _apply_cached_roi(frame: np.ndarray, cached_roi: RoadROI) -> RoadROI:
        """Reuse the latest mask geometry while cropping the current frame."""
        x1, y1, x2, y2 = cached_roi.bounds
        height, width = frame.shape[:2]
        if (
            cached_roi.mask.shape != (height, width)
            or x2 <= x1
            or y2 <= y1
        ):
            return RoadROI(
                frame,
                (0, 0, width, height),
                np.ones((height, width), dtype=np.uint8),
                True,
            )

        crop = frame[y1:y2, x1:x2].copy()
        crop_mask = cached_roi.mask[y1:y2, x1:x2]
        if not cached_roi.used_fallback:
            crop[crop_mask == 0] = 0
        return RoadROI(
            crop,
            cached_roi.bounds,
            cached_roi.mask,
            cached_roi.used_fallback,
        )

    @staticmethod
    def annotate(frame: np.ndarray, roi: RoadROI, result) -> np.ndarray:
        annotated = frame.copy()
        if not roi.used_fallback:
            overlay = annotated.copy()
            overlay[roi.mask > 0] = (
                0.7 * overlay[roi.mask > 0] + np.array([0, 100, 0])
            ).astype(np.uint8)
            annotated = cv2.addWeighted(annotated, 0.7, overlay, 0.3, 0)

        x1, y1, x2, y2 = roi.bounds
        boxes = result.boxes
        if boxes is None:
            return annotated

        coordinates = boxes.xyxy.cpu().numpy()
        confidences = boxes.conf.cpu().tolist()
        class_ids = boxes.cls.int().cpu().tolist()
        names = result.names

        for bbox, confidence, class_id in zip(
            coordinates,
            confidences,
            class_ids,
        ):
            box_x1, box_y1, box_x2, box_y2 = map(int, bbox)
            box_x1 = max(0, min(frame.shape[1] - 1, box_x1 + x1))
            box_y1 = max(0, min(frame.shape[0] - 1, box_y1 + y1))
            box_x2 = max(0, min(frame.shape[1] - 1, box_x2 + x1))
            box_y2 = max(0, min(frame.shape[0] - 1, box_y2 + y1))

            cv2.rectangle(
                annotated,
                (box_x1, box_y1),
                (box_x2, box_y2),
                (0, 0, 255),
                2,
            )
            label = f"{names[class_id]} {confidence:.2f}"
            cv2.putText(
                annotated,
                label,
                (box_x1, max(20, box_y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 255),
                2,
            )
        return annotated