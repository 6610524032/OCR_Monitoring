import sqlite3
from collections.abc import Mapping

from src.logger import create_logger
from src.server.database import get_connection


logger = create_logger(
    "server.repositories.camera"
)


REQUIRED_CAMERA_FIELDS = (
    "camera_name",
    "camera_ip",
    "camera_port",
    "camera_username",
    "camera_password",
    "rtsp_path",
)


def _close_connection(conn):
    """
    Close a database connection safely.

    A close error must not hide the original
    database error.
    """
    if conn is None:
        return

    try:
        conn.close()

    except Exception:
        logger.exception(
            "Failed to close camera database connection"
        )


def _rollback_connection(conn):
    """
    Roll back a database transaction safely.
    """
    if conn is None:
        return

    try:
        conn.rollback()

    except Exception:
        logger.exception(
            "Failed to roll back camera transaction"
        )


def _validate_camera_data(data):
    """
    Validate and normalize camera configuration
    before writing it to the database.
    """
    if not isinstance(
        data,
        Mapping,
    ):
        raise ValueError(
            "Camera configuration must be an object"
        )

    missing_fields = [
        field
        for field in REQUIRED_CAMERA_FIELDS
        if str(
            data.get(
                field,
                "",
            )
        ).strip() == ""
    ]

    if missing_fields:
        raise ValueError(
            "Missing camera fields: "
            + ", ".join(
                missing_fields
            )
        )

    try:
        camera_port = int(
            data.get(
                "camera_port"
            )
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise ValueError(
            "Camera port must be a valid number"
        ) from error

    if not (
        1 <= camera_port <= 65535
    ):
        raise ValueError(
            "Camera port must be between 1 and 65535"
        )

    rtsp_path = str(
        data.get(
            "rtsp_path",
            "",
        )
    ).strip()

    if not rtsp_path.startswith("/"):
        rtsp_path = (
            "/"
            + rtsp_path
        )

    return {
        "camera_name": str(
            data.get(
                "camera_name",
                "",
            )
        ).strip(),

        "camera_ip": str(
            data.get(
                "camera_ip",
                "",
            )
        ).strip(),

        "camera_port": camera_port,

        "camera_username": str(
            data.get(
                "camera_username",
                "",
            )
        ).strip(),

        "camera_password": str(
            data.get(
                "camera_password",
                "",
            )
        ),

        "rtsp_path": rtsp_path,
    }


def get_active_camera():
    conn = None

    try:
        conn = get_connection()
        conn.row_factory = sqlite3.Row

        cur = conn.cursor()

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

        camera = dict(
            row
        )

        logger.info(
            "Active camera configuration loaded"
        )

        return camera

    except sqlite3.Error:
        logger.exception(
            (
                "Database error while loading "
                "camera configuration"
            )
        )

        raise

    except Exception:
        logger.exception(
            (
                "Unexpected error while loading "
                "camera configuration"
            )
        )

        raise

    finally:
        _close_connection(
            conn
        )


def save_camera_config(data):
    conn = None

    try:
        camera_data = (
            _validate_camera_data(
                data
            )
        )

        conn = get_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT id
            FROM camera
            WHERE id = 1
        """)

        exists = (
            cur.fetchone()
            is not None
        )

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
                    is_active = 1,
                    updated_at = datetime('now')
                WHERE id = 1
            """, (
                camera_data[
                    "camera_name"
                ],
                camera_data[
                    "camera_ip"
                ],
                camera_data[
                    "camera_port"
                ],
                camera_data[
                    "camera_username"
                ],
                camera_data[
                    "camera_password"
                ],
                camera_data[
                    "rtsp_path"
                ],
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
                camera_data[
                    "camera_name"
                ],
                camera_data[
                    "camera_ip"
                ],
                camera_data[
                    "camera_port"
                ],
                camera_data[
                    "camera_username"
                ],
                camera_data[
                    "camera_password"
                ],
                camera_data[
                    "rtsp_path"
                ],
            ))

            logger.info(
                "Camera configuration created"
            )

        conn.commit()

        logger.info(
            (
                "Camera configuration transaction "
                "committed successfully"
            )
        )

        return {
            "ok": True,
            "camera_id": 1,
        }

    except ValueError:
        _rollback_connection(
            conn
        )

        logger.exception(
            "Invalid camera configuration data"
        )

        raise

    except sqlite3.IntegrityError:
        _rollback_connection(
            conn
        )

        logger.exception(
            (
                "Camera configuration violates "
                "a database constraint"
            )
        )

        raise

    except sqlite3.OperationalError:
        _rollback_connection(
            conn
        )

        logger.exception(
            (
                "Database operational error while "
                "saving camera configuration"
            )
        )

        raise

    except sqlite3.Error:
        _rollback_connection(
            conn
        )

        logger.exception(
            (
                "Database error while saving "
                "camera configuration"
            )
        )

        raise

    except Exception:
        _rollback_connection(
            conn
        )

        logger.exception(
            (
                "Unexpected error while saving "
                "camera configuration"
            )
        )

        raise

    finally:
        _close_connection(
            conn
        )