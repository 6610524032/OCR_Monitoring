import os
from pathlib import Path
from typing import Iterable


# =====================================================
# PROJECT ROOT
# =====================================================

# config.py อยู่ที่:
# src/server/config.py
#
# parents[2] คือโฟลเดอร์หลักของโปรเจกต์
PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)


# =====================================================
# ENVIRONMENT HELPERS
# =====================================================

def _get_env_text(
    name: str,
    default: str,
) -> str:
    value = os.getenv(
        name
    )

    if value is None:
        return default

    value = value.strip()

    if not value:
        return default

    return value


def _get_env_bool(
    name: str,
    default: bool,
) -> bool:
    raw_value = os.getenv(
        name
    )

    if raw_value is None:
        return default

    normalized = (
        raw_value
        .strip()
        .casefold()
    )

    if normalized in {
        "1",
        "true",
        "yes",
        "y",
        "on",
        "enable",
        "enabled",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
        "n",
        "off",
        "disable",
        "disabled",
    }:
        return False

    return default


def _get_env_int(
    name: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw_value = os.getenv(
        name
    )

    if raw_value is None:
        value = default

    else:
        try:
            value = int(
                raw_value.strip()
            )

        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            value = default

    if (
        minimum is not None
        and value < minimum
    ):
        value = minimum

    if (
        maximum is not None
        and value > maximum
    ):
        value = maximum

    return value


def _resolve_path(
    value: str | Path,
) -> Path:
    expanded_value = os.path.expandvars(
        str(
            value
        )
    )

    path = Path(
        expanded_value
    ).expanduser()

    if not path.is_absolute():
        path = (
            PROJECT_ROOT
            / path
        )

    return path.resolve(
        strict=False
    )


def _get_env_path(
    name: str,
    default: Path,
) -> Path:
    raw_value = os.getenv(
        name
    )

    if raw_value is None:
        return _resolve_path(
            default
        )

    raw_value = raw_value.strip()

    if not raw_value:
        return _resolve_path(
            default
        )

    return _resolve_path(
        raw_value
    )


def _parse_capture_minutes(
    raw_value: str | None,
    default: Iterable[int],
) -> list[int]:
    """
    รองรับค่า เช่น:

    RTSP_CAPTURE_MINUTES=0
    RTSP_CAPTURE_MINUTES=0,15,30,45
    RTSP_CAPTURE_MINUTES=*
    RTSP_CAPTURE_MINUTES=all
    """
    default_minutes = sorted({
        int(
            minute
        )
        for minute in default
        if 0 <= int(
            minute
        ) <= 59
    })

    if raw_value is None:
        return default_minutes

    normalized = (
        raw_value
        .strip()
        .casefold()
    )

    if not normalized:
        return default_minutes

    if normalized in {
        "*",
        "all",
        "every",
        "every-minute",
    }:
        return list(
            range(
                60
            )
        )

    minutes = set()

    for item in normalized.split(
        ","
    ):
        item = item.strip()

        if not item:
            continue

        try:
            minute = int(
                item
            )

        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            continue

        if 0 <= minute <= 59:
            minutes.add(
                minute
            )

    if not minutes:
        return default_minutes

    return sorted(
        minutes
    )


# =====================================================
# DATA STORAGE
# =====================================================

DATA_DIR = _get_env_path(
    "DATA_DIR",
    PROJECT_ROOT / "data",
)


# =====================================================
# DATABASE
# =====================================================

DB_DIR = _get_env_path(
    "DB_DIR",
    DATA_DIR / "database",
)

DB_PATH = _get_env_path(
    "DB_PATH",
    DB_DIR / "database.db",
)


# =====================================================
# IMAGE STORAGE
# =====================================================

RAW_IMAGES_DIR = _get_env_path(
    "RAW_IMAGES_DIR",
    DATA_DIR / "raw_images",
)

CALIBRATED_IMAGES_DIR = _get_env_path(
    "CALIBRATED_IMAGES_DIR",
    DATA_DIR / "calibrated_images",
)

INCOMING_IMAGES_DIR = _get_env_path(
    "INCOMING_IMAGES_DIR",
    DATA_DIR / "incoming",
)

# รองรับไฟล์เดิมที่ยัง import INCOMING_DIR
INCOMING_DIR = INCOMING_IMAGES_DIR


# =====================================================
# REQUIRED DIRECTORIES
# =====================================================

REQUIRED_DIRECTORIES = (
    DB_DIR,
    RAW_IMAGES_DIR,
    CALIBRATED_IMAGES_DIR,
    INCOMING_IMAGES_DIR,
)


def ensure_runtime_directories(
    strict: bool = False,
) -> tuple[str, ...]:
    """
    พยายามสร้างโฟลเดอร์ที่ระบบจำเป็นต้องใช้

    strict=False:
        ไม่ทำให้ Import ล้มเหลวทันที และคืนรายการ
        Error เพื่อให้ส่วนเริ่มระบบนำไปบันทึก Log

    strict=True:
        ยก RuntimeError เมื่อสร้างโฟลเดอร์ไม่ได้
    """
    errors = []

    for directory in REQUIRED_DIRECTORIES:
        try:
            directory.mkdir(
                parents=True,
                exist_ok=True,
            )

        except OSError as error:
            errors.append(
                (
                    f"{directory}: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )
            )

    if (
        strict
        and errors
    ):
        raise RuntimeError(
            (
                "Cannot create required "
                "runtime directories: "
                + "; ".join(
                    errors
                )
            )
        )

    return tuple(
        errors
    )


# พยายามสร้างตอน Import แต่ไม่ทำให้ Process ปิดทันที
DIRECTORY_INITIALIZATION_ERRORS = (
    ensure_runtime_directories(
        strict=False
    )
)


# =====================================================
# RTSP CAPTURE
# =====================================================

# Worker ตรวจสอบเวลาทุก 5 วินาที
PROCESS_CHECK_INTERVAL = 5

# เปิดใช้งานการจับภาพตามเวลา
RTSP_CAPTURE_ENABLED = True

# จับภาพทุก ๆ 0 และ 30 นาทีของชั่วโมง
RTSP_CAPTURE_MINUTES = [0, 30]


# =====================================================
# API SECURITY
# =====================================================

DEFAULT_API_KEY = "dev-api-key"

API_KEY = _get_env_text(
    "API_KEY",
    DEFAULT_API_KEY,
)

API_KEY_USING_DEFAULT = (
    API_KEY == DEFAULT_API_KEY
)

API_SERVER_URL = (
    _get_env_text(
        "API_SERVER_URL",
        "http://127.0.0.1:5001",
    )
    .rstrip(
        "/"
    )
)


# =====================================================
# OCR
# =====================================================

OCR_ENGINE = (
    _get_env_text(
        "OCR_ENGINE",
        "trocr",
    )
    .casefold()
)

OCR_MODEL_NAME = _get_env_text(
    "OCR_MODEL_NAME",
    "microsoft/trocr-base-printed",
)


# =====================================================
# MODEL CACHE
# =====================================================

MODEL_CACHE_DIR = _get_env_path(
    "MODEL_CACHE_DIR",
    (
        PROJECT_ROOT
        / "model_cache"
        / "huggingface"
    ),
)