import sqlite3
from pathlib import Path
import re
from datetime import datetime, timedelta

from src.server.config import (
    DB_DIR,
    DB_PATH,
    RAW_IMAGES_DIR,
    CALIBRATED_IMAGES_DIR
)


def get_connection():
    DB_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    return sqlite3.connect(DB_PATH)


def table_exists(cur, table_name):
    cur.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name=?
        """,
        (table_name,)
    )

    return cur.fetchone() is not None


def normalize_image_path(image_path, base_dir):
    if not image_path:
        return None

    path = Path(str(image_path))

    try:
        if path.is_absolute():
            return str(path.relative_to(base_dir)).replace("\\", "/")
    except ValueError:
        pass

    text = str(image_path).replace("\\", "/")
    marker = str(base_dir).replace("\\", "/") + "/"

    if marker in text:
        return text.split(marker, 1)[1]

    return text


def to_relative_path(path):
    if path is None:
        return ""

    text = str(path).replace("\\", "/")

    if "raw_images" in text:
        return normalize_image_path(
            image_path=path,
            base_dir=RAW_IMAGES_DIR
        )

    if "calibrated_images" in text:
        return normalize_image_path(
            image_path=path,
            base_dir=CALIBRATED_IMAGES_DIR
        )

    return text


def parse_numeric_value(value):
    try:
        if value is None:
            return None

        text = str(value).strip()

        if text == "":
            return None

        return float(text)

    except Exception:
        return None


def is_normal_run(status, missing_tags):
    if status != "NORMAL":
        return False

    if missing_tags:
        return False

    return True


def build_tag_signature(tags):
    parts = []

    for tag in tags:
        parts.append(
            f"{tag['tag_name']}|{tag.get('unit', '')}|{tag.get('display_order', '')}"
        )

    return "||".join(parts)


def make_summary_column_name(tag_name, unit):
    tag_name = str(tag_name).strip()
    unit = str(unit or "").strip()

    if unit:
        return f"{tag_name} ({unit})"

    return tag_name


def get_or_create_active_summary_table(tags):
    tag_signature = build_tag_signature(tags)

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM summary_versions
        WHERE is_active = 1
        ORDER BY id DESC
        LIMIT 1
    """)

    active = cur.fetchone()

    if active and active["tag_signature"] == tag_signature:
        conn.close()
        return active["table_name"]

    cur.execute("UPDATE summary_versions SET is_active = 0")

    cur.execute("""
        SELECT COUNT(*)
        FROM summary_versions
    """)

    count = cur.fetchone()[0]
    version_number = count + 1
    table_name = f"ocr_summary_v{version_number}"

    columns_sql = []

    for tag in tags:
        column_name = make_summary_column_name(
            tag["tag_name"],
            tag.get("unit", "")
        )

        columns_sql.append(
            f'"{column_name}" TEXT'
        )

    create_sql = f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            run_id INTEGER PRIMARY KEY,
            ocr_status TEXT,
            review_status TEXT,
            edit_type TEXT,
            ocr_time TEXT,
            {", ".join(columns_sql)},
            created_at TEXT
        )
    """

    cur.execute(create_sql)

    cur.execute("""
        INSERT INTO summary_versions (
            table_name,
            tag_signature,
            is_active,
            created_at
        )
        VALUES (?, ?, 1, datetime('now'))
    """, (
        table_name,
        tag_signature
    ))

    conn.commit()
    conn.close()

    return table_name
