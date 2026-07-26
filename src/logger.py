from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Final


# src/logger.py
# parents[0] = src
# parents[1] = project root
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

LOGS_DIR: Final[Path] = PROJECT_ROOT / "logs"
LOG_FILE: Final[Path] = LOGS_DIR / "application.log"

LOG_FORMAT: Final[str] = (
    "%(asctime)s | "
    "%(levelname)s | "
    "%(name)s | "
    "%(message)s"
)

DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

_HANDLER_MARKER: Final[str] = "_ocr_monitoring_file_handler"


def get_logger(name: str) -> logging.Logger:
    """
    สร้างและคืนค่า Logger กลางของโปรแกรม

    Log ปัจจุบัน:
        logs/application.log

    Log ของวันก่อนหน้า:
        logs/application.log.YYYY-MM-DD

    ระบบจะแยกไฟล์ใหม่ทุกเที่ยงคืน
    และเก็บย้อนหลัง 30 วัน
    """

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # ไม่ส่ง Log ต่อไปยัง Root Logger
    # เพื่อป้องกันข้อความซ้ำ
    logger.propagate = False

    # ถ้า Logger นี้เคยติดตั้ง File Handler แล้ว
    # ให้ใช้ตัวเดิม ไม่เพิ่มซ้ำ
    for handler in logger.handlers:
        if getattr(handler, _HANDLER_MARKER, False):
            return logger

    try:
        LOGS_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        formatter = logging.Formatter(
            fmt=LOG_FORMAT,
            datefmt=DATE_FORMAT,
        )

        file_handler = TimedRotatingFileHandler(
            filename=LOG_FILE,
            when="midnight",
            interval=1,
            backupCount=30,
            encoding="utf-8",
            delay=True,
        )

        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)

        # ใช้สำหรับตรวจว่า Handler ถูกเพิ่มแล้วหรือยัง
        setattr(
            file_handler,
            _HANDLER_MARKER,
            True,
        )

        logger.addHandler(file_handler)

    except Exception:
        # หากสร้างโฟลเดอร์หรือ File Handler ไม่สำเร็จ
        # ต้องไม่ทำให้โปรแกรมหลักหยุดทำงาน
        if not logger.handlers:
            logger.addHandler(
                logging.NullHandler()
            )

    return logger