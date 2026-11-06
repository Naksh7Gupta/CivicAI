"""Deterministic grouping of repeated pothole tracks into incidents."""
import math
from datetime import datetime, timedelta
from uuid import uuid4

from app.database.database import get_connection


def haversine_m(lat1, lon1, lat2, lon2):
    radius_m = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_m * math.asin(min(1.0, math.sqrt(value)))


def can_merge_locations(new_location, candidate, radius_m=12.0, max_accuracy_m=20.0):
    """Only merge same-source, non-poor-accuracy coordinates within the radius."""
    if not new_location or not candidate:
        return False
    required = ("latitude", "longitude", "accuracy_m", "location_source", "is_simulated")
    if any(new_location.get(key) is None or candidate.get(key) is None for key in required):
        return False
    if new_location["location_source"] != candidate["location_source"]:
        return False
    if bool(new_location["is_simulated"]) != bool(candidate["is_simulated"]):
        return False
    if new_location["accuracy_m"] > max_accuracy_m or candidate["accuracy_m"] > max_accuracy_m:
        return False
    return haversine_m(
        new_location["latitude"],
        new_location["longitude"],
        candidate["latitude"],
        candidate["longitude"],
    ) <= radius_m


class IncidentAggregator:
    def __init__(self, radius_m=12.0, max_accuracy_m=20.0, lookback_days=30):
        self.radius_m = float(radius_m)
        self.max_accuracy_m = float(max_accuracy_m)
        self.lookback_days = int(lookback_days)

    def assign_track(self, pothole_track_id):
        connection = get_connection()
        try:
            track = connection.execute(
                """
                SELECT id, first_seen, last_seen, best_confidence
                FROM pothole_tracks WHERE id = ?
                """,
                (pothole_track_id,),
            ).fetchone()
            if track is None:
                return None

            location_row = connection.execute(
                """
                SELECT ol.*
                FROM observation_locations ol
                JOIN observations o ON o.id = ol.observation_id
                WHERE o.pothole_id = ?
                ORDER BY (ol.accuracy_m IS NULL), ol.accuracy_m ASC,
                         ol.frame_elapsed_ms DESC
                LIMIT 1
                """,
                (pothole_track_id,),
            ).fetchone()
            location = dict(location_row) if location_row is not None else None

            existing = connection.execute(
                "SELECT incident_id FROM incident_tracks WHERE pothole_track_id = ?",
                (pothole_track_id,),
            ).fetchone()
            if existing is not None:
                incident_id = existing["incident_id"]
                incident = connection.execute(
                    "SELECT * FROM incidents WHERE id = ?", (incident_id,)
                ).fetchone()
                self._update_incident(connection, incident, track, location)
                connection.commit()
                return incident_id

            candidate_id = None
            if (
                location
                and location["accuracy_m"] is not None
                and location["accuracy_m"] <= self.max_accuracy_m
            ):
                first_seen = datetime.fromisoformat(track["first_seen"])
                cutoff = (first_seen - timedelta(days=self.lookback_days)).isoformat()
                candidates = connection.execute(
                    """
                    SELECT * FROM incidents
                    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                      AND location_accuracy_m IS NOT NULL
                      AND location_accuracy_m <= ?
                      AND location_source = ?
                      AND is_simulated = ?
                      AND last_seen >= ?
                    """,
                    (
                        self.max_accuracy_m,
                        location["location_source"],
                        int(location["is_simulated"]),
                        cutoff,
                    ),
                ).fetchall()
                candidate_dict = dict(location)
                for candidate in candidates:
                    candidate_location = {
                        "latitude": candidate["latitude"],
                        "longitude": candidate["longitude"],
                        "accuracy_m": candidate["location_accuracy_m"],
                        "location_source": candidate["location_source"],
                        "is_simulated": candidate["is_simulated"],
                    }
                    if can_merge_locations(
                        candidate_dict,
                        candidate_location,
                        radius_m=self.radius_m,
                        max_accuracy_m=self.max_accuracy_m,
                    ):
                        distance = haversine_m(
                            location["latitude"],
                            location["longitude"],
                            candidate["latitude"],
                            candidate["longitude"],
                        )
                        if candidate_id is None or distance < best_distance:
                            candidate_id = candidate["id"]
                            best_distance = distance

            if candidate_id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO incidents (
                        incident_key, category, first_seen, last_seen,
                        best_confidence, latitude, longitude,
                        location_accuracy_m, location_source, is_simulated,
                        location_semantics, status, merge_method,
                        created_at, updated_at
                    ) VALUES (?, 'pothole', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'needs_review', ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        track["first_seen"],
                        track["last_seen"],
                        track["best_confidence"],
                        location["latitude"] if location else None,
                        location["longitude"] if location else None,
                        location["accuracy_m"] if location else None,
                        location["location_source"] if location else None,
                        int(location["is_simulated"]) if location else None,
                        location["location_semantics"] if location else "vehicle_position_estimate",
                        "located_track" if location else "single_track",
                        track["first_seen"],
                        track["last_seen"],
                    ),
                )
                incident_id = cursor.lastrowid
            else:
                incident_id = candidate_id
                incident = connection.execute(
                    "SELECT * FROM incidents WHERE id = ?", (incident_id,)
                ).fetchone()
                self._update_incident(connection, incident, track, location)
                connection.execute(
                    "UPDATE incidents SET merge_method = 'gps_radius_merge' WHERE id = ?",
                    (incident_id,),
                )

            connection.execute(
                """
                INSERT INTO incident_tracks (incident_id, pothole_track_id)
                VALUES (?, ?)
                """,
                (incident_id, pothole_track_id),
            )
            connection.commit()
            return incident_id
        finally:
            connection.close()

    @staticmethod
    def _update_incident(connection, incident, track, location):
        if incident is None:
            return
        first_seen = min(incident["first_seen"], track["first_seen"])
        last_seen = max(incident["last_seen"], track["last_seen"])
        best_confidence = max(incident["best_confidence"], track["best_confidence"])
        updates_location = False
        if location and incident["latitude"] is None:
            updates_location = True
        elif (
            location
            and incident["location_source"] == location["location_source"]
            and incident["is_simulated"] == int(location["is_simulated"])
            and location["accuracy_m"] is not None
            and (
                incident["location_accuracy_m"] is None
                or location["accuracy_m"] < incident["location_accuracy_m"]
            )
        ):
            updates_location = True

        if updates_location:
            connection.execute(
                """
                UPDATE incidents
                SET first_seen = ?, last_seen = ?, best_confidence = ?,
                    latitude = ?, longitude = ?, location_accuracy_m = ?,
                    location_source = ?, is_simulated = ?, location_semantics = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    first_seen, last_seen, best_confidence,
                    location["latitude"], location["longitude"], location["accuracy_m"],
                    location["location_source"], int(location["is_simulated"]),
                    location["location_semantics"], last_seen, incident["id"],
                ),
            )
        else:
            connection.execute(
                """
                UPDATE incidents
                SET first_seen = ?, last_seen = ?, best_confidence = ?, updated_at = ?
                WHERE id = ?
                """,
                (first_seen, last_seen, best_confidence, last_seen, incident["id"]),
            )
