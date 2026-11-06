"""CivicAI application entry point."""
import uuid

import cv2
import torch

from app.core.config import BASE_DIR
from app.database.database import initialize_database

from app.ingestion.stream_receiver import StreamReceiver

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

    video_path = BASE_DIR.parent / "references" / "20250118_171213_clip01of01.mp4"
    output_path = BASE_DIR.parent / "references" / "pothole_detection_output.mp4"
    image_path = BASE_DIR.parent / "references" / "image.png"
    image_output_path = (
        BASE_DIR.parent / "references" / "pothole_detection_image2.png"
    )
    receiver = StreamReceiver(str(video_path))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("Using device:", device)
    if device.type == "cuda":
        print("GPU:", torch.cuda.get_device_name(0))

    detector = PotholeDetector(device=device)

    manager = DetectionManager(session_id)

    receiver.start()

    print("Video connected.")
    print("Saving annotated video to:", output_path)
    writer = None

    try:

        while True:

            frame = receiver.read()

            if frame is None:
                break

            # Run detection and tracking

            result = detector.detect(frame)

            # Save detections and crops

            manager.process(
                frame,
                result
            )

            # Display detections

            annotated_frame = result.plot()

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

        image = cv2.imread(str(image_path))
        if image is None:
            raise RuntimeError(f"Unable to open image: {image_path}")

        image_result = detector.detect_image(image)
        manager.process(image, image_result)

        if not cv2.imwrite(
            str(image_output_path),
            image_result.plot()
        ):
            raise RuntimeError(
                f"Unable to save annotated image: {image_output_path}"
            )

        print("Saving annotated image to:", image_output_path)
        print("CivicAI stopped.")


if __name__ == "__main__":

    main()