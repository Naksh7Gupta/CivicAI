"""CivicAI application entry point."""
import uuid

import cv2
import torch

from app.core.config import GPS_TRACE_PATH, OUTPUT_VIDEO_PATH, VIDEO_PATH
from app.database.database import initialize_database

from app.ingestion.stream_receiver import StreamReceiver
from app.ingestion.road_roi import RoadROIProcessor

from app.detection.detector import PotholeDetector

from app.services.detection_manager import DetectionManager
from app.services.gps_association import GPSAssociator, load_gps_csv
from app.database.reporting_repository import save_gps_samples


def main():
    print("Starting CivicAI Backend...")

    # Initialize database

    initialize_database()

    # Unique ID for this stream session

    session_id = str(uuid.uuid4())

    print("Session:", session_id)

    # Initialize components

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

    detector = PotholeDetector(device=device)
    roi_processor = RoadROIProcessor(device=device)

    gps_associator = None
    if GPS_TRACE_PATH is not None:
        if not GPS_TRACE_PATH.is_file():
            raise FileNotFoundError(f"GPS trace was not found: {GPS_TRACE_PATH}")
        gps_samples = load_gps_csv(GPS_TRACE_PATH)
        save_gps_samples(session_id, gps_samples)
        gps_associator = GPSAssociator(gps_samples)
        print(f"Loaded {len(gps_samples)} GPS samples from {GPS_TRACE_PATH}")
    else:
        print("No GPS trace configured; detections will be stored without coordinates.")

    manager = DetectionManager(session_id, gps_associator=gps_associator)

    receiver.start()

    print("Video connected:", VIDEO_PATH)
    print("Saving annotated video to:", output_path)
    writer = None

    try:

        while True:

            frame, frame_elapsed_ms = receiver.read_with_timestamp()

            if frame is None:
                break

            # Segment the road, then detect only inside the resulting crop.
            roi = roi_processor.process(frame)
            result = detector.detect(roi.image)

            # Save detections and crops

            manager.process(
                frame,
                result,
                offset=roi.bounds[:2],
                frame_elapsed_ms=frame_elapsed_ms,
            )

            # Display detections

            annotated_frame = roi_processor.annotate(frame, roi, result)

            if writer is None:
                height, width = annotated_frame.shape[:2]
                writer = cv2.VideoWriter(
                    str(output_path),
                    cv2.VideoWriter_fourcc(*"mp4v"),
                    30.0,
                    (width, height)
                )

                if not writer.isOpened():
                    raise RuntimeError(
                        f"Unable to create output video: {output_path}"
                    )

            writer.write(annotated_frame)

    finally:

        receiver.release()

        if writer is not None:
            writer.release()

        print("CivicAI stopped.")


if __name__ == "__main__":

    main()