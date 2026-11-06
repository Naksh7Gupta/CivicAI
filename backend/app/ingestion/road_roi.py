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
        height, width = frame.shape[:2]
        full_bounds = (0, 0, width, height)
        full_mask = np.ones((height, width), dtype=np.uint8)

        if self.model is None:
            return RoadROI(frame, full_bounds, full_mask, True)

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb_frame, (1024, 512))
        tensor = torch.from_numpy(resized).permute(2, 0, 1).float()
        mean = tensor.new_tensor(
            [123.675, 116.28, 103.53]
        )[:, None, None]
        std = tensor.new_tensor(
            [58.395, 57.12, 57.375]
        )[:, None, None]
        tensor = ((tensor - mean) / std).unsqueeze(0)
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