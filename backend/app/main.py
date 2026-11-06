"""CivicAI application entry point."""
import uuid

import cv2
import torch

from app.core.config import OUTPUT_VIDEO_PATH, VIDEO_PATH
from app.database.database import initialize_database

from app.ingestion.stream_receiver import StreamReceiver
from app.ingestion.road_roi import RoadROIProcessor

from app.detection.detector import PotholeDetector

from app.services.detection_manager import DetectionManager


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

    manager = DetectionManager(session_id)

    receiver.start()

    print("Video connected:", VIDEO_PATH)
    print("Saving annotated video to:", output_path)
    writer = None

    try:

        while True:

            frame = receiver.read()

            if frame is None:
                break

            # Segment the road, then detect only inside the resulting crop.
            roi = roi_processor.process(frame)
            result = detector.detect(roi.image)

            # Save detections and crops

            manager.process(
                frame,
                result,
                offset=roi.bounds[:2]
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