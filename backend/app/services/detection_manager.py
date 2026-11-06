"""Detection workflow: preserve model inference and persist observations safely."""
from datetime import datetime, timezone

from app.database.repository import (
    add_observation,
    assign_track_incident,
    create_incident,
    create_track,
    get_track,
    update_incident_after_observation,
    update_track,
)
from app.services.crop_storage import CropStorage


class DetectionManager:
    def __init__(self, session_id, gps_provider=None):
        self.session_id = session_id
        self.gps_provider = gps_provider
        self.crop_storage = CropStorage()
        self._untracked_counter = 0

    def process(
        self,
        frame,
        result,
        offset=(0, 0),
        video_timestamp_seconds=None,
        timestamp_source=None,
    ):
        boxes = result.boxes
        if boxes is None:
            return

        coordinates = boxes.xyxy.cpu().numpy()
        if boxes.id is None:
            # Never reuse positional IDs across frames: doing so would falsely
            # merge unrelated detections when the tracker has no IDs.
            track_ids = []
            for _ in coordinates:
                self._untracked_counter += 1
                track_ids.append(-self._untracked_counter)
        else:
            track_ids = boxes.id.int().cpu().tolist()
        confidences = boxes.conf.cpu().tolist()

        location = None
        if self.gps_provider is not None:
            location = self.gps_provider.match(video_timestamp_seconds)

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
                incident_id = create_incident(
                    self.session_id, timestamp, confidence, location
                )
                pothole_id = create_track(
                    self.session_id,
                    track_id,
                    timestamp,
                    confidence,
                    bbox,
                    crop_path,
                    incident_id,
                )
            else:
                pothole_id = existing["id"]
                incident_id = existing["incident_id"]
                crop_path = None
                if confidence > existing["best_confidence"]:
                    crop_path = self.crop_storage.save_crop(
                        frame, bbox, self.session_id, track_id
                    )
                update_track(pothole_id, timestamp, confidence, bbox, crop_path)
                if incident_id is None:
                    incident_id = create_incident(
                        self.session_id, timestamp, confidence, location
                    )
                    assign_track_incident(pothole_id, incident_id)

            add_observation(
                pothole_id,
                timestamp,
                confidence,
                bbox,
                video_timestamp_seconds=video_timestamp_seconds,
                timestamp_source=timestamp_source,
                location=location,
            )
            update_incident_after_observation(
                incident_id, timestamp, confidence, location
            )
