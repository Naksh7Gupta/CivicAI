"""Detection workflow management."""
from datetime import datetime, timezone

from app.database.repository import (
    create_track,
    get_track,
    update_track,
    add_observation
)

from app.services.crop_storage import CropStorage


class DetectionManager:

    def __init__(self, session_id):

        self.session_id = session_id

        self.crop_storage = CropStorage()

    def process(self, frame, result):

        boxes = result.boxes

        if boxes is None:
            return

        coordinates = boxes.xyxy.cpu().numpy()

        if boxes.id is None:
            track_ids = list(range(1, len(coordinates) + 1))
        else:
            track_ids = boxes.id.int().cpu().tolist()

        confidences = boxes.conf.cpu().tolist()

        for bbox, track_id, confidence in zip(
            coordinates,
            track_ids,
            confidences
        ):

            x1, y1, x2, y2 = map(
                int,
                bbox
            )

            bbox = (x1, y1, x2, y2)

            timestamp = datetime.now(
                timezone.utc
            ).isoformat()

            existing = get_track(
                self.session_id,
                track_id
            )

            if existing is None:

                crop_path = self.crop_storage.save_crop(
                    frame,
                    bbox,
                    self.session_id,
                    track_id
                )

                pothole_id = create_track(

                    self.session_id,
                    track_id,
                    timestamp,
                    confidence,
                    bbox,
                    crop_path

                )

                print(
                    f"[NEW POTHOLE] ID={track_id} "
                    f"Confidence={confidence:.2f}"
                )

            else:

                pothole_id = existing["id"]

                crop_path = None

                # Save a new crop only when confidence improves.

                if confidence > existing["best_confidence"]:

                    crop_path = self.crop_storage.save_crop(
                        frame,
                        bbox,
                        self.session_id,
                        track_id
                    )

                update_track(
                    pothole_id,
                    timestamp,
                    confidence,
                    bbox,
                    crop_path
                )

            add_observation(
                pothole_id,
                timestamp,
                confidence,
                bbox
            )