"""Detection crop storage."""
import cv2

from pathlib import Path

from app.core.config import CROP_DIR


class CropStorage:

    def __init__(self):

        CROP_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

    def save_crop(
        self,
        frame,
        bbox,
        session_id,
        track_id
    ):

        x1, y1, x2, y2 = bbox

        height, width = frame.shape[:2]

        # Ensure coordinates stay inside the image

        x1 = max(0, min(x1, width))
        x2 = max(0, min(x2, width))

        y1 = max(0, min(y1, height))
        y2 = max(0, min(y2, height))

        if x2 <= x1 or y2 <= y1:
            return None

        crop = frame[y1:y2, x1:x2]

        filename = f"{session_id}_{track_id}.jpg"

        output_path = CROP_DIR / filename

        temporary_path = output_path.with_suffix(".tmp.jpg")

        success = cv2.imwrite(
            str(temporary_path),
            crop
        )

        if not success:
            return None

        temporary_path.replace(output_path)

        return str(output_path)