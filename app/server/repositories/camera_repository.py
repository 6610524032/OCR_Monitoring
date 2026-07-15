import sqlite3

from app.server.database import get_connection


def get_active_camera():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT
                id,
                camera_name,
                camera_ip,
                camera_username,
                camera_password,
                rtsp_path
            FROM camera
            WHERE is_active = 1
            ORDER BY id
            LIMIT 1
        """)

        row = cur.fetchone()

        if row is None:
            return None

        return dict(row)

    finally:
        conn.close()