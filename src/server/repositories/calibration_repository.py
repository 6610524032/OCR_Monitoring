import sqlite3

from src.server.database import get_connection


def get_active_calibration():
    """
    Return the latest active calibration record.

    Returns:
        dict | None: Active calibration data, or None when
        no active calibration exists.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT *
            FROM calibration
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
        """)

        row = cur.fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        conn.close()


def save_calibration_data(data):
    """
    Deactivate the previous calibration and save a new
    active calibration record.

    Args:
        data (dict): Must contain image_path and four points.
    """
    points = data["points"]

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            UPDATE calibration
            SET is_active = 0
        """)

        cur.execute("""
            INSERT INTO calibration (
                image_path,
                p1_x,
                p1_y,
                p2_x,
                p2_y,
                p3_x,
                p3_y,
                p4_x,
                p4_y,
                created_at,
                updated_at,
                is_active
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                datetime('now'),
                datetime('now'),
                1
            )
        """, (
            data.get("image_path"),
            points[0]["x"],
            points[0]["y"],
            points[1]["x"],
            points[1]["y"],
            points[2]["x"],
            points[2]["y"],
            points[3]["x"],
            points[3]["y"]
        ))

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()