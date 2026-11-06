"""Application configuration."""
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]

MODEL_PATH = BASE_DIR / "models" / "pothole.pt"
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