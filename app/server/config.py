import os
from pathlib import Path


# =====================================================
# PROJECT ROOT
# =====================================================

BASE_DIR = Path(__file__).resolve().parents[1]

DATA_DIR = BASE_DIR / "server" / "data"


# =====================================================
# DATABASE
# =====================================================

DB_DIR = DATA_DIR / "database"
DB_PATH = DB_DIR / "database.db"


# =====================================================
# IMAGE STORAGE
# =====================================================

RAW_IMAGES_DIR = DATA_DIR / "raw_images"

CALIBRATED_IMAGES_DIR = (
    DATA_DIR / "calibrated_images"
)

INCOMING_DIR = DATA_DIR / "incoming"

# =====================================================
# RTSP CAPTURE
# =====================================================

PROCESS_CHECK_INTERVAL = 5

RTSP_CAPTURE_ENABLED = True
RTSP_CAPTURE_MINUTES = [0]

# =====================================================
# API SECURITY
# =====================================================

API_KEY = os.environ.get(
    "API_KEY",
    "dev-api-key"
)

API_SERVER_URL = os.environ.get(
    "API_SERVER_URL",
    "http://127.0.0.1:5001"
)

# =====================================================
# MODEL CACHE
# =====================================================

MODEL_CACHE_DIR = Path(
    os.environ.get(
        "MODEL_CACHE_DIR",
        str(BASE_DIR.parent / "model_cache" / "huggingface")
    )
)