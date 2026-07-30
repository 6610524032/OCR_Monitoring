import sqlite3

from src.logger import create_logger
from src.server.config import DB_PATH
from src.server.database import get_connection


logger = create_logger(
    "server.init_db"
)


def _safe_rollback(
    conn,
) -> None:
    """
    Roll back safely without hiding
    the original initialization error.
    """
    if conn is None:
        return

    try:
        conn.rollback()

    except Exception:
        logger.exception(
            (
                "Failed to roll back database "
                "initialization transaction"
            )
        )


def _safe_close(
    conn,
) -> None:
    """
    Close safely without hiding
    the original initialization error.
    """
    if conn is None:
        return

    try:
        conn.close()

    except Exception:
        logger.exception(
            (
                "Failed to close database "
                "initialization connection"
            )
        )


def _get_table_columns(
    cursor,
    table_name: str,
) -> set[str]:
    """
    Return the existing column names
    for a database table.
    """
    cursor.execute(
        f'PRAGMA table_info("{table_name}")'
    )

    return {
        str(row[1])
        for row in cursor.fetchall()
    }


def _add_column_if_missing(
    cursor,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> bool:
    """
    Add a column only when it does not
    already exist.

    Returns True when a column was added.
    """
    existing_columns = (
        _get_table_columns(
            cursor,
            table_name,
        )
    )

    if column_name in existing_columns:
        return False

    logger.info(
        (
            "Adding database column: "
            "table=%s, column=%s"
        ),
        table_name,
        column_name,
    )

    cursor.execute(
        (
            f'ALTER TABLE "{table_name}" '
            f'ADD COLUMN "{column_name}" '
            f"{column_definition}"
        )
    )

    return True


def init_database():
    """
    Create and migrate the local database schema.

    Initialization is transactional. When any
    statement fails, all changes in this run
    are rolled back.
    """
    logger.info(
        "Initializing database schema"
    )

    conn = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Prevent multiple API processes from
        # changing the schema at the same time.
        cursor.execute(
            "BEGIN IMMEDIATE"
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS calibration (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                image_path TEXT,

                p1_x REAL,
                p1_y REAL,
                p2_x REAL,
                p2_y REAL,
                p3_x REAL,
                p3_y REAL,
                p4_x REAL,
                p4_y REAL,

                output_width INTEGER DEFAULT 900,
                output_height INTEGER DEFAULT 700,

                is_active INTEGER DEFAULT 1,

                created_at TEXT,
                updated_at TEXT
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                tag_name TEXT NOT NULL,
                unit TEXT,
                display_order INTEGER DEFAULT 0,

                sensor_api_key TEXT,

                roi_x1 REAL NOT NULL,
                roi_y1 REAL NOT NULL,
                roi_x2 REAL NOT NULL,
                roi_y2 REAL NOT NULL,

                is_active INTEGER DEFAULT 1,

                created_at TEXT,
                updated_at TEXT
            )
            """
        )

        _add_column_if_missing(
            cursor=cursor,
            table_name="user_tags",
            column_name="sensor_api_key",
            column_definition="TEXT",
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS camera (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                camera_name TEXT NOT NULL,
                camera_ip TEXT NOT NULL,
                camera_port INTEGER NOT NULL DEFAULT 554,

                camera_username TEXT NOT NULL,
                camera_password TEXT NOT NULL,

                rtsp_path TEXT NOT NULL,

                is_active INTEGER DEFAULT 1,

                created_at TEXT,
                updated_at TEXT
            )
            """
        )

        _add_column_if_missing(
            cursor=cursor,
            table_name="camera",
            column_name="camera_port",
            column_definition=(
                "INTEGER NOT NULL DEFAULT 554"
            ),
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ocr_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                raw_image_path TEXT,
                calibrated_image_path TEXT,

                captured_at TEXT,
                ocr_time TEXT,

                status TEXT DEFAULT 'NORMAL',

                missing_tags TEXT,
                alert_message TEXT,

                created_at TEXT
            )
            """
        )

        _add_column_if_missing(
            cursor=cursor,
            table_name="ocr_runs",
            column_name="captured_at",
            column_definition="TEXT",
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ocr_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                run_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,

                tag_name TEXT NOT NULL,
                unit TEXT,

                value TEXT,
                raw_text TEXT,

                created_at TEXT,

                FOREIGN KEY (run_id)
                    REFERENCES ocr_runs(id),

                FOREIGN KEY (tag_id)
                    REFERENCES user_tags(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS outbound_sensor_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                run_id INTEGER NOT NULL,
                tag_id INTEGER NOT NULL,

                tag_name TEXT NOT NULL,
                sensor_api_key TEXT NOT NULL,

                capture_timestamp INTEGER NOT NULL,
                value REAL NOT NULL,

                status TEXT NOT NULL DEFAULT 'PENDING',
                retry_count INTEGER NOT NULL DEFAULT 0,

                http_status INTEGER,
                response_message TEXT,
                last_error TEXT,

                created_at TEXT,
                last_attempt_at TEXT,
                sent_at TEXT,

                FOREIGN KEY (run_id)
                    REFERENCES ocr_runs(id),

                FOREIGN KEY (tag_id)
                    REFERENCES user_tags(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS summary_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                table_name TEXT NOT NULL,
                tag_signature TEXT NOT NULL,

                is_active INTEGER DEFAULT 1,

                created_at TEXT
            )
            """
        )

        conn.commit()

        logger.info(
            "Database schema initialized successfully"
        )

    except sqlite3.IntegrityError:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Database initialization failed "
                "because of a constraint violation"
            )
        )

        raise

    except sqlite3.OperationalError:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Database initialization failed "
                "because of an SQLite operational error"
            )
        )

        raise

    except sqlite3.Error:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Database initialization failed "
                "because of an SQLite error"
            )
        )

        raise

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Unexpected database "
                "initialization error"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )


def ensure_database():
    """
    Prepare the database directory and schema.
    """
    try:
        DB_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        init_database()

        logger.info(
            "Database is ready"
        )

    except OSError:
        logger.exception(
            (
                "Cannot prepare database "
                "directory: %s"
            ),
            DB_PATH.parent,
        )

        raise

    except Exception:
        # init_database already logs the detailed
        # database error. This records the startup
        # stage that failed.
        logger.error(
            "Database preparation did not complete"
        )

        raise


if __name__ == "__main__":
    ensure_database()