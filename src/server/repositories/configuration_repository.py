import sqlite3

from src.logger import create_logger
from src.server.database import get_connection


logger = create_logger(
    "server.repositories.configuration"
)


def _safe_rollback(
    conn,
) -> None:
    if conn is None:
        return

    try:
        conn.rollback()

    except sqlite3.Error:
        logger.exception(
            (
                "Failed to roll back "
                "configuration reset"
            )
        )


def _safe_close(
    conn,
) -> None:
    if conn is None:
        return

    try:
        conn.close()

    except sqlite3.Error:
        logger.exception(
            (
                "Failed to close configuration "
                "database connection"
            )
        )


def _row_count(
    cursor,
) -> int:
    try:
        row_count = int(
            cursor.rowcount
        )

    except (
        TypeError,
        ValueError,
    ):
        return 0

    return max(
        0,
        row_count,
    )


def reset_configuration_data():
    """
    Reset active system configuration without
    deleting OCR history or referenced Tag records.

    Calibration and Tags are deactivated so historical
    OCR values remain valid. Camera credentials are
    cleared and every camera record is deactivated.
    """
    conn = None

    try:
        conn = get_connection()

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        logger.info(
            (
                "Resetting active system "
                "configuration"
            )
        )

        calibration_cursor = conn.execute("""
            UPDATE calibration
            SET
                is_active = 0,
                updated_at = datetime('now')
            WHERE is_active = 1
        """)

        tag_cursor = conn.execute("""
            UPDATE user_tags
            SET
                is_active = 0,
                updated_at = datetime('now')
            WHERE is_active = 1
        """)

        camera_cursor = conn.execute("""
            UPDATE camera
            SET
                camera_name = '',
                camera_ip = '',
                camera_port = 554,
                camera_username = '',
                camera_password = '',
                rtsp_path = '',
                is_active = 0,
                updated_at = datetime('now')
            WHERE
                COALESCE(is_active, 0) <> 0
                OR COALESCE(camera_name, '') <> ''
                OR COALESCE(camera_ip, '') <> ''
                OR COALESCE(camera_port, 554) <> 554
                OR COALESCE(camera_username, '') <> ''
                OR COALESCE(camera_password, '') <> ''
                OR COALESCE(rtsp_path, '') <> ''
        """)

        reset_counts = {
            "calibrations_deactivated": (
                _row_count(
                    calibration_cursor
                )
            ),
            "tags_deactivated": (
                _row_count(
                    tag_cursor
                )
            ),
            "cameras_reset": (
                _row_count(
                    camera_cursor
                )
            ),
        }

        conn.commit()

        changed = (
            sum(
                reset_counts.values()
            )
            > 0
        )

        logger.info(
            (
                "System configuration reset "
                "completed: calibration=%d, "
                "tags=%d, cameras=%d"
            ),
            reset_counts[
                "calibrations_deactivated"
            ],
            reset_counts[
                "tags_deactivated"
            ],
            reset_counts[
                "cameras_reset"
            ],
        )

        return {
            "ok": True,
            "changed": changed,
            "message": (
                "System configuration reset"
                if changed
                else (
                    "System configuration "
                    "was already empty"
                )
            ),
            **reset_counts,
        }

    except sqlite3.Error:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Database error while "
                "resetting configuration"
            )
        )

        raise

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Unexpected error while "
                "resetting configuration"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )