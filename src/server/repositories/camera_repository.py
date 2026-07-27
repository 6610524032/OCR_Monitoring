import sqlite3

from src.logger import create_logger
from src.server.database import get_connection


logger = create_logger(
    "server.repositories.camera"
)


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
            logger.info(
                "No active camera configuration found"
            )
            return None

        logger.info(
            "Active camera configuration loaded"
        )

        return dict(row)

    except Exception:
        logger.exception(
            "Failed to load camera configuration"
        )
        raise

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

            logger.info(
                "Camera configuration updated"
            )

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

            logger.info(
                "Camera configuration created"
            )

        conn.commit()

    except Exception:
        conn.rollback()

        logger.exception(
            "Failed to save camera configuration"
        )

        raise

    finally:
        conn.close()