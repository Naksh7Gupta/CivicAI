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
        self.fallback_track_id = -1

    def process(self, frame, result, offset=(0, 0), video_time_ms=None):

        boxes = result.boxes

        if boxes is None:
            return

        coordinates = boxes.xyxy.cpu().numpy()

        if boxes.id is None:
            # Never reuse frame-local IDs across frames; that would falsely merge incidents.
            track_ids = []
            for _ in coordinates:
                track_ids.append(self.fallback_track_id)
                self.fallback_track_id -= 1
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
            x1 += offset[0]
            x2 += offset[0]
            y1 += offset[1]
            y2 += offset[1]

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

            observation_id = add_observation(
                pothole_id,
                timestamp,
                confidence,
                bbox,
                video_time_ms=video_time_ms
            )
            if video_time_ms is not None:
                from app.services.gps_repository import associate_observation
                associate_observation(observation_id, self.session_id, video_time_ms)