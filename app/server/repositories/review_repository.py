import re
from datetime import datetime

import sqlite3

from app.server.config import (
    RAW_IMAGES_DIR,
    CALIBRATED_IMAGES_DIR
)

from app.server.database import (
    get_connection
)

from app.server.repositories.summary_repository import (
    save_summary_row
)

def get_review_list():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            ocr_time,
            status,
            missing_tags,
            alert_message,
            raw_image_path,
            calibrated_image_path
        FROM ocr_runs
        WHERE review_status = 'PENDING'
        AND status != 'NORMAL'
        ORDER BY ocr_time DESC
    """)

    rows = cur.fetchall()
    conn.close()

    items = []

    for row in rows:
        raw_path = row["raw_image_path"] or ""
        calibrated_path = row["calibrated_image_path"] or ""

        items.append({
            "id": row["id"],
            "ocr_time": row["ocr_time"],
            "status": row["status"],
            "missing_tags": row["missing_tags"] or "",
            "alert_message": row["alert_message"] or "",
            "raw_image_url": "/raw_images/" + raw_path if raw_path else None,
            "calibrated_image_url": "/calibrated_images/" + calibrated_path if calibrated_path else None
        })

    return items


def get_review_count():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) AS total
        FROM ocr_runs
        WHERE review_status = 'PENDING'
        AND status != 'NORMAL'
    """)

    total = cur.fetchone()["total"]

    conn.close()

    return total


def save_review_values(run_id, values):
    if not values:
        return {
            "ok": False,
            "message": "No values received",
            "invalid_tags": []
        }

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT id
        FROM ocr_runs
        WHERE id = ?
        LIMIT 1
    """, (run_id,))

    run = cur.fetchone()

    if run is None:
        conn.close()
        return {
            "ok": False,
            "message": "Run not found",
            "invalid_tags": []
        }

    invalid_tags = []

    for item in values:
        tag_name = str(item.get("tag_name", "")).strip()
        value = str(item.get("value", "")).strip()

        if tag_name == "":
            continue

        if value == "" or not re.search(r"\d", value):
            invalid_tags.append(tag_name)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for item in values:
        tag_name = str(item.get("tag_name", "")).strip()
        value = str(item.get("value", "")).strip()

        if tag_name == "":
            continue

        cur.execute("""
            SELECT id, unit
            FROM user_tags
            WHERE tag_name = ?
            AND is_active = 1
            ORDER BY id DESC
            LIMIT 1
        """, (tag_name,))

        tag = cur.fetchone()

        if tag is None:
            continue

        cur.execute("""
            SELECT id
            FROM ocr_values
            WHERE run_id = ?
            AND tag_name = ?
            LIMIT 1
        """, (run_id, tag_name))

        existing = cur.fetchone()

        if existing:
            cur.execute("""
                UPDATE ocr_values
                SET value = ?,
                    raw_text = ?,
                    created_at = ?
                WHERE id = ?
            """, (
                value,
                "MANUAL_EDIT",
                now,
                existing["id"]
            ))
        else:
            cur.execute("""
                INSERT INTO ocr_values (
                    run_id,
                    tag_id,
                    tag_name,
                    unit,
                    value,
                    raw_text,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                tag["id"],
                tag_name,
                tag["unit"] or "",
                value,
                "MANUAL_EDIT",
                now
            ))

    if invalid_tags:
        cur.execute("""
            UPDATE ocr_runs
            SET status = 'ALERT',
                review_status = 'PENDING',
                missing_tags = ?,
                alert_message = ?
            WHERE id = ?
        """, (
            ",".join(invalid_tags),
            "Missing or invalid: " + ", ".join(invalid_tags),
            run_id
        ))
    else:
        cur.execute("""
            UPDATE ocr_runs
            SET status = 'NORMAL',
                review_status = 'FIXED',
                missing_tags = '',
                alert_message = ''
            WHERE id = ?
        """, (run_id,))

    conn.commit()
    conn.close()

    save_summary_row(
        run_id=run_id,
        edit_type="MANUAL_EDIT"
    )

    return {
        "ok": True,
        "message": "Values saved",
        "invalid_tags": invalid_tags
    }


def accept_review_run(run_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE ocr_runs
        SET review_status = 'ACCEPTED'
        WHERE id = ?
    """, (run_id,))

    conn.commit()
    conn.close()

    save_summary_row(
        run_id=run_id,
        edit_type="ACCEPTED"
    )


def delete_review_run(run_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            raw_image_path,
            calibrated_image_path
        FROM ocr_runs
        WHERE id = ?
    """, (run_id,))

    row = cur.fetchone()

    if row is None:
        conn.close()
        return False

    raw_path = row["raw_image_path"]
    calibrated_path = row["calibrated_image_path"]

    cur.execute(
        "DELETE FROM ocr_values WHERE run_id = ?",
        (run_id,)
    )

    cur.execute(
        "DELETE FROM ocr_runs WHERE id = ?",
        (run_id,)
    )

    conn.commit()
    conn.close()

    try:
        if raw_path:
            raw_file = RAW_IMAGES_DIR / raw_path
            raw_file.unlink(missing_ok=True)

        if calibrated_path:
            calibrated_file = CALIBRATED_IMAGES_DIR / calibrated_path
            calibrated_file.unlink(missing_ok=True)

    except Exception :
        pass

    return True