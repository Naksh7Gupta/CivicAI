"""CivicAI application entry point."""
import uuid

import cv2
import torch

from app.core.config import (
    GPS_MAX_ACCURACY_M,
    GPS_MAX_DELTA_SECONDS,
    GPS_TRACK_CSV,
    OUTPUT_VIDEO_PATH,
    VIDEO_PATH,
    VIDEO_START_TIME_UTC,
)
from app.database.database import initialize_database
from app.detection.detector import PotholeDetector
from app.ingestion.road_roi import RoadROIProcessor
from app.ingestion.stream_receiver import StreamReceiver
from app.services.detection_manager import DetectionManager
from app.services.gps_provider import GPSLocationProvider


def main():
    print("Starting CivicAI Backend...")
    initialize_database()
    session_id = str(uuid.uuid4())
    print("Session:", session_id)

    output_path = OUTPUT_VIDEO_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not VIDEO_PATH.is_file():
        raise FileNotFoundError(
            f"Video file was not found: {VIDEO_PATH}. "
            "Set VIDEO_PATH in backend/.env to an uploaded video."
        )
    receiver = StreamReceiver(str(VIDEO_PATH))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Using device:", device)
    if device.type == "cuda":
        print("GPU:", torch.cuda.get_device_name(0))

    gps_provider = None
    if GPS_TRACK_CSV is not None:
        gps_provider = GPSLocationProvider.from_csv(
            GPS_TRACK_CSV,
            video_start_time_utc=VIDEO_START_TIME_UTC,
            max_delta_seconds=GPS_MAX_DELTA_SECONDS,
            max_accuracy_m=GPS_MAX_ACCURACY_M,
        )
        print(f"Loaded {len(gps_provider.fixes)} timestamped GPS samples.")
    else:
        print("GPS track not configured; detections will be stored without coordinates.")

    # The existing T4-compatible YOLO + road-ROI inference path is unchanged.
    detector = PotholeDetector(device=device)
    roi_processor = RoadROIProcessor(device=device)
    manager = DetectionManager(session_id, gps_provider=gps_provider)

    receiver.start()
    print("Video connected:", VIDEO_PATH)
    print("Saving annotated video to:", output_path)
    writer = None
    try:
        while True:
            frame = receiver.read()
            if frame is None:
                break
            roi = roi_processor.process(frame)
            result = detector.detect(roi.image)
            manager.process(
                frame,
                result,
                offset=roi.bounds[:2],
                video_timestamp_seconds=receiver.last_timestamp_seconds,
                timestamp_source=receiver.timestamp_source,
            )
            annotated_frame = roi_processor.annotate(frame, roi, result)
            if writer is None:
                height, width = annotated_frame.shape[:2]
                writer = cv2.VideoWriter(
                    str(output_path),
                    cv2.VideoWriter_fourcc(*"mp4v"),
                    receiver.fps or 30.0,
                    (width, height),
                )
                if not writer.isOpened():
                    raise RuntimeError(f"Unable to create output video: {output_path}")
            writer.write(annotated_frame)
    finally:
        receiver.release()
        if writer is not None:
            writer.release()
        print("CivicAI stopped.")


if __name__ == "__main__":
    main()
