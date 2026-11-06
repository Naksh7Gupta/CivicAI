"""Application configuration."""
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]

MODEL_PATH = BASE_DIR / "models" / "pothole.pt"
VIDEO_PATH = Path(
    os.getenv(
        "VIDEO_PATH",
        str(BASE_DIR.parent / "references" / "20250118_171213_clip01of01.mp4"),
    )
)
OUTPUT_VIDEO_PATH = Path(
    os.getenv(
        "OUTPUT_VIDEO_PATH",
        str(BASE_DIR.parent / "references" / "pothole_detection_output.mp4"),
    )
)
ROAD_SEGMENTATION_MODEL_PATH = Path(
    os.getenv(
        "ROAD_SEGMENTATION_MODEL_PATH",
        str(BASE_DIR / "models" / "segmentation_model.pth"),
    )
)

DATABASE_PATH = BASE_DIR / "data" / "civicai.db"

CROP_DIR = BASE_DIR / "storage" / "potholes"

FRAME_WIDTH = 640

FRAME_HEIGHT = 640

CONFIDENCE_THRESHOLD = 0.7

IOU_THRESHOLD = 0.7

TRACKER = "bytetrack.yaml"

ROAD_SEGMENTATION_CLASS_ID = int(
    os.getenv("ROAD_SEGMENTATION_CLASS_ID", "0")
)
ROI_PADDING_RATIO = float(os.getenv("ROI_PADDING_RATIO", "0.15"))
ROI_MIN_AREA_RATIO = float(os.getenv("ROI_MIN_AREA_RATIO", "0.05"))
ROI_MIN_WIDTH = int(os.getenv("ROI_MIN_WIDTH", "64"))
ROI_MIN_HEIGHT = int(os.getenv("ROI_MIN_HEIGHT", "64"))
ROI_SEGMENTATION_INTERVAL = int(
    os.getenv("ROI_SEGMENTATION_INTERVAL", "20")
)
GPS_TRACE_PATH_RAW = os.getenv("GPS_TRACE_PATH")
GPS_TRACE_PATH = (
    Path(GPS_TRACE_PATH_RAW).expanduser()
    if GPS_TRACE_PATH_RAW
    else None
)
if GPS_TRACE_PATH is not None and not GPS_TRACE_PATH.is_absolute():
    GPS_TRACE_PATH = BASE_DIR / GPS_TRACE_PATH
