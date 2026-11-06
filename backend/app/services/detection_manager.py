"""Detection workflow management."""
from datetime import datetime, timezone

from app.database.repository import (
    create_track,
    get_track,
    update_track,
    add_observation,
)
from app.database.reporting_repository import save_observation_location
from app.services.crop_storage import CropStorage
from app.services.incident_aggregation import IncidentAggregator


class DetectionManager:
    def __init__(self, session_id, gps_associator=None):
        self.session_id = session_id
        self.crop_storage = CropStorage()
        self.gps_associator = gps_associator
        self.incident_aggregator = IncidentAggregator()

    def process(self, frame, result, offset=(0, 0), frame_elapsed_ms=None):
        boxes = result.boxes
        if boxes is None:
            return

        coordinates = boxes.xyxy.cpu().numpy()
        if boxes.id is None:
            track_ids = list(range(1, len(coordinates) + 1))
        else:
            track_ids = boxes.id.int().cpu().tolist()
        confidences = boxes.conf.cpu().tolist()

        for bbox, track_id, confidence in zip(coordinates, track_ids, confidences):
            x1, y1, x2, y2 = map(int, bbox)
            x1 += offset[0]
            x2 += offset[0]
            y1 += offset[1]
            y2 += offset[1]
            bbox = (x1, y1, x2, y2)
            timestamp = datetime.now(timezone.utc).isoformat()

            existing = get_track(self.session_id, track_id)
            if existing is None:
                crop_path = self.crop_storage.save_crop(
                    frame, bbox, self.session_id, track_id
                )
                pothole_id = create_track(
                    self.session_id, track_id, timestamp, confidence, bbox, crop_path
                )
                print(
                    f"[NEW POTHOLE] ID={track_id} "
                    f"Confidence={confidence:.2f}"
                )
            else:
                pothole_id = existing["id"]
                crop_path = None
                if confidence > existing["best_confidence"]:
                    crop_path = self.crop_storage.save_crop(
                        frame, bbox, self.session_id, track_id
                    )
                update_track(
                    pothole_id, timestamp, confidence, bbox, crop_path
                )

            observation_id = add_observation(
                pothole_id, timestamp, confidence, bbox
            )

            if self.gps_associator is not None and frame_elapsed_ms is not None:
                gps_match = self.gps_associator.associate(frame_elapsed_ms)
                if gps_match is not None:
                    save_observation_location(
                        self.session_id,
                        observation_id,
                        frame_elapsed_ms,
                        gps_match,
                    )

            self.incident_aggregator.assign_track(pothole_id)
