"""Application configuration."""
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]
MODEL_PATH = BASE_DIR / "models" / "pothole.pt"
DATABASE_PATH = BASE_DIR / "data" / "civicai.db"
CROP_DIR = BASE_DIR / "storage" / "potholes"
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.35"))
IOU_THRESHOLD = 0.45
FRAME_WIDTH = 640
FRAME_HEIGHT = 640
TRACKER = "bytetrack.yaml"
RECORDING_START_TIME = os.getenv("CIVICAI_RECORDING_START_TIME")
SESSION_ID = os.getenv("CIVICAI_SESSION_ID")
