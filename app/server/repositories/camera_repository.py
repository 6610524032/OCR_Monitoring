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
                camera_port,
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


def save_camera_config(data):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT id
            FROM camera
            WHERE id = 1
        """)

        exists = cur.fetchone()

        if exists:

            cur.execute("""
                UPDATE camera
                SET
                    camera_name = ?,
                    camera_ip = ?,
                    camera_port = ?,
                    camera_username = ?,
                    camera_password = ?,
                    rtsp_path = ?,
                    updated_at = datetime('now')
                WHERE id = 1
            """, (
                data["camera_name"],
                data["camera_ip"],
                data["camera_port"],
                data["camera_username"],
                data["camera_password"],
                data["rtsp_path"]
            ))

        else:

            cur.execute("""
                INSERT INTO camera (
                    id,
                    camera_name,
                    camera_ip,
                    camera_port,
                    camera_username,
                    camera_password,
                    rtsp_path,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (
                    1,
                    ?, ?, ?, ?, ?, ?,
                    1,
                    datetime('now'),
                    datetime('now')
                )
            """, (
                data["camera_name"],
                data["camera_ip"],
                data["camera_port"],
                data["camera_username"],
                data["camera_password"],
                data["rtsp_path"]
            ))

        conn.commit()

    finally:
        conn.close()