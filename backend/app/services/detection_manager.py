"""Persist detections without changing the YOLO inference path."""
from datetime import datetime, timezone

from app.database.repository import (
    add_observation, create_track, get_track, link_track_to_incident, update_track,
)
from app.geolocation.association import parse_timestamp
from app.geolocation.repository import associate_session_fix
from app.services.crop_storage import CropStorage
from app.services.incident_aggregator import create_incident, record_incident_observation


class DetectionManager:
    def __init__(self, session_id):
        self.session_id = session_id
        self.crop_storage = CropStorage()
        self._untracked_counter = 0

    def process(self, frame, result, frame_timestamp=None):
        boxes = result.boxes
        if boxes is None:
            return
        coordinates = boxes.xyxy.cpu().numpy()
        if boxes.id is None:
            # Without tracker IDs, do not reuse positional IDs across frames.
            track_ids = []
            for _ in coordinates:
                self._untracked_counter += 1
                track_ids.append(-self._untracked_counter)
        else:
            track_ids = boxes.id.int().cpu().tolist()
        confidences = boxes.conf.cpu().tolist()

        frame_time_iso = None
        gps_association = None
        if frame_timestamp is not None:
            frame_time_iso = parse_timestamp(frame_timestamp).isoformat()
            gps_association = associate_session_fix(self.session_id, frame_time_iso)
        timestamp = frame_time_iso or datetime.now(timezone.utc).isoformat()

        for raw_bbox, track_id, confidence in zip(coordinates, track_ids, confidences):
            bbox = tuple(map(int, raw_bbox))
            existing = get_track(self.session_id, track_id)
            if existing is None:
                crop_path = self.crop_storage.save_crop(frame, bbox, self.session_id, track_id)
                incident_id = create_incident(
                    self.session_id, track_id, timestamp, confidence, gps_association
                )
                pothole_id = create_track(
                    self.session_id, track_id, timestamp, confidence, bbox,
                    crop_path, incident_id=incident_id,
                )
                print(f"[NEW POTHOLE TRACK] ID={track_id} Confidence={confidence:.2f}")
            else:
                pothole_id = existing["id"]
                incident_id = existing["incident_id"]
                if incident_id is None:
                    incident_id = create_incident(
                        self.session_id, track_id, timestamp, confidence, gps_association
                    )
                    link_track_to_incident(pothole_id, incident_id)
                crop_path = None
                if confidence > existing["best_confidence"]:
                    crop_path = self.crop_storage.save_crop(frame, bbox, self.session_id, track_id)
                update_track(pothole_id, timestamp, confidence, bbox, crop_path)

            record_incident_observation(incident_id, timestamp, confidence, gps_association)
            add_observation(
                pothole_id, timestamp, confidence, bbox,
                incident_id=incident_id, frame_timestamp=frame_time_iso,
                gps_association=gps_association,
            )
