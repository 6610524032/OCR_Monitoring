import os
from pathlib import Path


# =====================================================
# PROJECT ROOT
# =====================================================

# config.py อยู่ที่ app/server/config.py
# parents[2] จึงย้อนกลับมาที่โฟลเดอร์หลักของโปรเจกต์
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"


# =====================================================
# DATABASE
# =====================================================

DB_DIR = DATA_DIR / "database"
DB_PATH = DB_DIR / "database.db"


# =====================================================
# IMAGE STORAGE
# =====================================================

RAW_IMAGES_DIR = DATA_DIR / "raw_images"
CALIBRATED_IMAGES_DIR = DATA_DIR / "calibrated_images"
INCOMING_IMAGES_DIR = DATA_DIR / "incoming"

# เก็บชื่อนี้ไว้ด้วย เผื่อไฟล์เดิมบางไฟล์ import INCOMING_DIR
INCOMING_DIR = INCOMING_IMAGES_DIR


# =====================================================
# CREATE REQUIRED DIRECTORIES
# =====================================================

DB_DIR.mkdir(parents=True, exist_ok=True)
RAW_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
CALIBRATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
INCOMING_IMAGES_DIR.mkdir(parents=True, exist_ok=True)


# =====================================================
# RTSP CAPTURE
# =====================================================

PROCESS_CHECK_INTERVAL = 5

RTSP_CAPTURE_ENABLED = True
RTSP_CAPTURE_MINUTES = [0]

# หากต้องการให้ตรวจทุกนาที ใช้:
# RTSP_CAPTURE_MINUTES = list(range(60))


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
# OCR MODEL
# =====================================================

OCR_MODEL_NAME = os.getenv(
    "OCR_MODEL_NAME",
    "microsoft/trocr-base-printed",
)


# =====================================================
# MODEL CACHE
# =====================================================

MODEL_CACHE_DIR = Path(
    os.environ.get(
        "MODEL_CACHE_DIR",
        str(
            PROJECT_ROOT
            / "model_cache"
            / "huggingface"
        )
    )
)
