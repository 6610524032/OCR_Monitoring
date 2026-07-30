import math
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.logger import create_logger
from src.server.config import (
    CALIBRATED_IMAGES_DIR,
    DB_DIR,
    DB_PATH,
    RAW_IMAGES_DIR,
)


logger = create_logger(
    "server.database"
)


SUMMARY_SCHEMA_VERSION = 2

DATABASE_TIMEOUT_SECONDS = 30
DATABASE_BUSY_TIMEOUT_MS = 30000

SUMMARY_BASE_COLUMNS = {
    "run_id",
    "ocr_status",
    "ocr_time",
    "created_at",
}


def _safe_rollback(
    conn,
) -> None:
    """
    Roll back a transaction without hiding
    the original database error.
    """
    if conn is None:
        return

    try:
        conn.rollback()

    except Exception:
        logger.exception(
            "Failed to roll back database transaction"
        )


def _safe_close(
    conn,
) -> None:
    """
    Close a connection without hiding
    the original database error.
    """
    if conn is None:
        return

    try:
        conn.close()

    except Exception:
        logger.exception(
            "Failed to close database connection"
        )


def _apply_connection_settings(
    conn,
) -> None:
    """
    Configure SQLite for concurrent API,
    Web, and Worker processes.
    """
    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        (
            "PRAGMA busy_timeout = "
            f"{DATABASE_BUSY_TIMEOUT_MS}"
        )
    )

    try:
        result = conn.execute(
            "PRAGMA journal_mode = WAL"
        ).fetchone()

        journal_mode = (
            str(result[0]).lower()
            if result
            else ""
        )

        if journal_mode != "wal":
            logger.warning(
                (
                    "SQLite WAL mode was not enabled; "
                    "current mode=%s"
                ),
                journal_mode or "unknown",
            )

    except sqlite3.Error as error:
        # WAL ช่วยลดปัญหา Database Locked
        # แต่หากเปิดไม่ได้ ยังให้ Connection ทำงาน
        # ด้วยโหมดเดิมต่อได้
        logger.warning(
            (
                "Cannot enable SQLite WAL mode: %s"
            ),
            error,
        )

    try:
        conn.execute(
            "PRAGMA synchronous = NORMAL"
        )

    except sqlite3.Error as error:
        logger.warning(
            (
                "Cannot configure SQLite "
                "synchronous mode: %s"
            ),
            error,
        )


def get_connection():
    """
    Open and configure a SQLite connection.

    The caller remains responsible for closing
    the returned connection.
    """
    conn = None

    try:
        DB_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        conn = sqlite3.connect(
            str(DB_PATH),
            timeout=(
                DATABASE_TIMEOUT_SECONDS
            ),
        )

        _apply_connection_settings(
            conn
        )

        return conn

    except OSError:
        logger.exception(
            (
                "Cannot create database "
                "directory: %s"
            ),
            DB_DIR,
        )

        _safe_close(
            conn
        )

        raise

    except sqlite3.Error:
        logger.exception(
            (
                "Cannot open SQLite "
                "database: %s"
            ),
            DB_PATH,
        )

        _safe_close(
            conn
        )

        raise

    except Exception:
        logger.exception(
            (
                "Unexpected error while opening "
                "database connection"
            )
        )

        _safe_close(
            conn
        )

        raise


def table_exists(
    cursor,
    table_name,
):
    clean_table_name = str(
        table_name or ""
    ).strip()

    if not clean_table_name:
        raise ValueError(
            "table_name is required"
        )

    cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
        """,
        (
            clean_table_name,
        ),
    )

    return (
        cursor.fetchone()
        is not None
    )


def normalize_image_path(
    image_path,
    base_dir,
):
    if not image_path:
        return None

    original_text = str(
        image_path
    ).replace(
        "\\",
        "/",
    )

    try:
        path = Path(
            str(image_path)
        )

        base_path = Path(
            base_dir
        ).resolve()

        if path.is_absolute():
            resolved_path = (
                path.resolve()
            )

            try:
                return (
                    resolved_path
                    .relative_to(
                        base_path
                    )
                    .as_posix()
                )

            except ValueError:
                return original_text

    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        logger.warning(
            (
                "Cannot normalize image path: %s"
            ),
            original_text,
        )

        return original_text

    base_text = str(
        base_dir
    ).replace(
        "\\",
        "/",
    ).rstrip("/")

    marker = (
        base_text
        + "/"
    )

    marker_position = (
        original_text.lower()
        .find(
            marker.lower()
        )
    )

    if marker_position >= 0:
        return original_text[
            marker_position
            + len(marker):
        ]

    return original_text


def to_relative_path(
    path,
):
    if path is None:
        return ""

    text = str(
        path
    ).replace(
        "\\",
        "/",
    )

    lower_text = (
        text.lower()
    )

    if "raw_images" in lower_text:
        return normalize_image_path(
            image_path=path,
            base_dir=RAW_IMAGES_DIR,
        )

    if (
        "calibrated_images"
        in lower_text
    ):
        return normalize_image_path(
            image_path=path,
            base_dir=(
                CALIBRATED_IMAGES_DIR
            ),
        )

    return text


def parse_numeric_value(
    value,
):
    if value is None:
        return None

    text = str(
        value
    ).strip()

    if not text:
        return None

    try:
        numeric_value = float(
            text
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None

    if not math.isfinite(
        numeric_value
    ):
        return None

    return numeric_value


def is_normal_run(
    status,
    missing_tags,
):
    return (
        str(
            status or ""
        ).strip().upper()
        == "NORMAL"
        and not missing_tags
    )


def _get_tag_value(
    tag,
    field_name,
    default=None,
):
    if isinstance(
        tag,
        Mapping,
    ):
        return tag.get(
            field_name,
            default,
        )

    try:
        return tag[
            field_name
        ]

    except (
        KeyError,
        IndexError,
        TypeError,
    ):
        return default


def _normalize_tags(
    tags,
) -> list[dict[str, Any]]:
    if not isinstance(
        tags,
        (
            list,
            tuple,
        ),
    ):
        raise ValueError(
            "tags must be a list"
        )

    if not tags:
        raise ValueError(
            (
                "Cannot create summary table "
                "without active tags"
            )
        )

    normalized_tags = []
    used_column_names = {
        column_name.casefold()
        for column_name
        in SUMMARY_BASE_COLUMNS
    }

    for index, tag in enumerate(
        tags
    ):
        if not (
            isinstance(
                tag,
                Mapping,
            )
            or hasattr(
                tag,
                "keys",
            )
        ):
            raise ValueError(
                (
                    f"tags[{index}] "
                    "must be an object"
                )
            )

        tag_name = str(
            _get_tag_value(
                tag,
                "tag_name",
                "",
            )
        ).strip()

        unit = str(
            _get_tag_value(
                tag,
                "unit",
                "",
            )
            or ""
        ).strip()

        display_order = (
            _get_tag_value(
                tag,
                "display_order",
                "",
            )
        )

        if not tag_name:
            raise ValueError(
                (
                    f"tags[{index}]."
                    "tag_name is required"
                )
            )

        column_name = (
            make_summary_column_name(
                tag_name,
                unit,
            )
        )

        normalized_column_name = (
            column_name.casefold()
        )

        if (
            normalized_column_name
            in used_column_names
        ):
            raise ValueError(
                (
                    "Duplicate summary column "
                    f"name: {column_name}"
                )
            )

        used_column_names.add(
            normalized_column_name
        )

        normalized_tags.append({
            "tag_name": tag_name,
            "unit": unit,
            "display_order": (
                display_order
            ),
            "column_name": (
                column_name
            ),
        })

    return normalized_tags


def build_tag_signature(
    tags,
):
    normalized_tags = (
        _normalize_tags(
            tags
        )
    )

    parts = [
        (
            f"{tag['tag_name']}|"
            f"{tag['unit']}|"
            f"{tag['display_order']}"
        )
        for tag in normalized_tags
    ]

    tag_signature = (
        "||".join(
            parts
        )
    )

    return (
        f"schema-{SUMMARY_SCHEMA_VERSION}"
        f"||{tag_signature}"
    )


def make_summary_column_name(
    tag_name,
    unit,
):
    clean_tag_name = str(
        tag_name or ""
    ).strip()

    clean_unit = str(
        unit or ""
    ).strip()

    if not clean_tag_name:
        raise ValueError(
            "tag_name is required"
        )

    if clean_unit:
        return (
            f"{clean_tag_name} "
            f"({clean_unit})"
        )

    return clean_tag_name


def _quote_identifier(
    identifier,
) -> str:
    """
    Safely quote an SQLite table or column name.
    """
    clean_identifier = str(
        identifier or ""
    ).strip()

    if not clean_identifier:
        raise ValueError(
            "SQL identifier is required"
        )

    escaped_identifier = (
        clean_identifier.replace(
            '"',
            '""',
        )
    )

    return (
        f'"{escaped_identifier}"'
    )


def _get_next_summary_table_name(
    cursor,
) -> str:
    cursor.execute(
        """
        SELECT COALESCE(
            MAX(id),
            0
        )
        FROM summary_versions
        """
    )

    row = cursor.fetchone()

    version_number = (
        int(
            row[0]
        )
        + 1
    )

    while True:
        table_name = (
            f"ocr_summary_v"
            f"{version_number}"
        )

        if not table_exists(
            cursor,
            table_name,
        ):
            return table_name

        version_number += 1


def get_or_create_active_summary_table(
    tags,
):
    normalized_tags = (
        _normalize_tags(
            tags
        )
    )

    tag_signature = (
        build_tag_signature(
            normalized_tags
        )
    )

    conn = None

    try:
        conn = get_connection()
        conn.row_factory = (
            sqlite3.Row
        )

        cursor = conn.cursor()

        # ป้องกันหลาย Process สร้าง Summary
        # Version ใหม่พร้อมกัน
        cursor.execute(
            "BEGIN IMMEDIATE"
        )

        cursor.execute(
            """
            SELECT
                table_name,
                tag_signature
            FROM summary_versions
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
            """
        )

        active = (
            cursor.fetchone()
        )

        if (
            active
            and active["tag_signature"]
            == tag_signature
        ):
            active_table_name = str(
                active["table_name"]
            )

            if table_exists(
                cursor,
                active_table_name,
            ):
                conn.commit()

                return (
                    active_table_name
                )

            logger.warning(
                (
                    "Active summary metadata "
                    "references a missing table: %s"
                ),
                active_table_name,
            )

        cursor.execute(
            """
            UPDATE summary_versions
            SET is_active = 0
            WHERE is_active = 1
            """
        )

        table_name = (
            _get_next_summary_table_name(
                cursor
            )
        )

        table_columns = [
            (
                '"run_id" '
                "INTEGER PRIMARY KEY"
            ),
            '"ocr_status" TEXT',
            '"ocr_time" TEXT',
        ]

        for tag in normalized_tags:
            quoted_column = (
                _quote_identifier(
                    tag[
                        "column_name"
                    ]
                )
            )

            table_columns.append(
                (
                    f"{quoted_column} "
                    "TEXT"
                )
            )

        table_columns.append(
            '"created_at" TEXT'
        )

        columns_sql = (
            ",\n                ".join(
                table_columns
            )
        )

        quoted_table_name = (
            _quote_identifier(
                table_name
            )
        )

        create_sql = f"""
            CREATE TABLE {quoted_table_name} (
                {columns_sql}
            )
        """

        cursor.execute(
            create_sql
        )

        cursor.execute(
            """
            INSERT INTO summary_versions (
                table_name,
                tag_signature,
                is_active,
                created_at
            )
            VALUES (
                ?,
                ?,
                1,
                datetime('now')
            )
            """,
            (
                table_name,
                tag_signature,
            ),
        )

        conn.commit()

        logger.info(
            (
                "Created active summary "
                "table: %s"
            ),
            table_name,
        )

        return table_name

    except ValueError:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Invalid summary table "
                "configuration"
            )
        )

        raise

    except sqlite3.IntegrityError:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Summary table violates "
                "a database constraint"
            )
        )

        raise

    except sqlite3.OperationalError:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "SQLite operational error while "
                "creating summary table"
            )
        )

        raise

    except sqlite3.Error:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Database error while creating "
                "summary table"
            )
        )

        raise

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Unexpected error while creating "
                "summary table"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )