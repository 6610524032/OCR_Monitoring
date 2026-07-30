import re
import sqlite3
from datetime import datetime
from typing import Any

from src.logger import create_logger
from src.server.database import (
    get_connection,
    get_or_create_active_summary_table,
    make_summary_column_name,
)


logger = create_logger(
    "server.repositories.summary"
)


MAX_SUMMARY_VALUE_LENGTH = 2_000
MAX_COLUMN_NAME_LENGTH = 255

SUMMARY_TABLE_PATTERN = re.compile(
    r"^ocr_summary_v[1-9][0-9]*$"
)


class SummaryRepositoryError(
    RuntimeError
):
    """
    Raised when a Summary row cannot be
    prepared or stored safely.
    """


class SummaryValidationError(
    ValueError
):
    """
    Raised when Summary input or schema
    information is invalid.
    """


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
                "Summary transaction"
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
                "Failed to close Summary "
                "database connection"
            )
        )


def _positive_integer(
    value: Any,
    field_name: str,
) -> int:
    if isinstance(
        value,
        bool,
    ):
        raise SummaryValidationError(
            (
                f"{field_name} must "
                "be an integer"
            )
        )

    if (
        isinstance(
            value,
            float,
        )
        and not value.is_integer()
    ):
        raise SummaryValidationError(
            (
                f"{field_name} must "
                "be an integer"
            )
        )

    try:
        parsed = int(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise SummaryValidationError(
            (
                f"{field_name} must "
                "be an integer"
            )
        ) from error

    if parsed <= 0:
        raise SummaryValidationError(
            (
                f"{field_name} must be "
                "greater than zero"
            )
        )

    return parsed


def _safe_text(
    value: Any,
    max_length: int,
) -> str:
    if value is None:
        return ""

    try:
        text = str(
            value
        ).strip()

    except Exception as error:
        raise SummaryValidationError(
            (
                "Summary value cannot "
                "be converted to text"
            )
        ) from error

    if "\x00" in text:
        raise SummaryValidationError(
            (
                "Summary value contains "
                "an invalid character"
            )
        )

    return text[
        :max_length
    ]


def _quote_identifier(
    identifier: Any,
) -> str:
    """
    Quote an SQLite identifier safely.

    Double quotes inside a column name are
    escaped by doubling them.
    """
    identifier_text = _safe_text(
        identifier,
        MAX_COLUMN_NAME_LENGTH,
    )

    if not identifier_text:
        raise SummaryValidationError(
            (
                "SQL identifier cannot "
                "be empty"
            )
        )

    escaped_identifier = (
        identifier_text.replace(
            '"',
            '""',
        )
    )

    return (
        f'"{escaped_identifier}"'
    )


def _validate_table_name(
    table_name: Any,
) -> str:
    normalized = _safe_text(
        table_name,
        128,
    )

    if not SUMMARY_TABLE_PATTERN.fullmatch(
        normalized
    ):
        raise SummaryValidationError(
            (
                "Summary table name "
                "is invalid"
            )
        )

    return normalized


def _summary_column_name(
    tag: dict[str, Any],
) -> str:
    try:
        column_name = (
            make_summary_column_name(
                tag.get(
                    "tag_name",
                    "",
                ),
                tag.get(
                    "unit",
                    "",
                ),
            )
        )

    except Exception as error:
        raise SummaryValidationError(
            (
                "Cannot create Summary "
                "column name"
            )
        ) from error

    normalized = _safe_text(
        column_name,
        MAX_COLUMN_NAME_LENGTH,
    )

    if not normalized:
        raise SummaryValidationError(
            (
                "Summary column name "
                "cannot be empty"
            )
        )

    return normalized


def _load_summary_data(
    run_id: int,
) -> tuple[
    dict[str, Any] | None,
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    conn = None

    try:
        conn = get_connection()

        conn.row_factory = (
            sqlite3.Row
        )

        run_row = conn.execute(
            """
            SELECT
                id,
                status,
                ocr_time,
                created_at
            FROM ocr_runs
            WHERE id = ?
            LIMIT 1
            """,
            (
                run_id,
            ),
        ).fetchone()

        if run_row is None:
            return (
                None,
                [],
                [],
            )

        value_rows = conn.execute(
            """
            SELECT
                id,
                tag_id,
                tag_name,
                unit,
                value
            FROM ocr_values
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (
                run_id,
            ),
        ).fetchall()

        tag_rows = conn.execute(
            """
            SELECT
                id,
                tag_name,
                unit,
                display_order
            FROM user_tags
            WHERE is_active = 1
            ORDER BY
                display_order ASC,
                id ASC
            """
        ).fetchall()

        return (
            dict(
                run_row
            ),
            [
                dict(
                    row
                )
                for row in value_rows
            ],
            [
                dict(
                    row
                )
                for row in tag_rows
            ],
        )

    except sqlite3.Error:
        logger.exception(
            (
                "Database error while "
                "loading Summary data: "
                "run_id=%s"
            ),
            run_id,
        )

        raise

    except Exception:
        logger.exception(
            (
                "Unexpected error while "
                "loading Summary data: "
                "run_id=%s"
            ),
            run_id,
        )

        raise

    finally:
        _safe_close(
            conn
        )


def _build_value_maps(
    values: list[
        dict[str, Any]
    ],
) -> tuple[
    dict[int, str],
    dict[str, str],
]:
    """
    Build two lookup maps.

    Tag ID is preferred so a renamed Tag can still
    receive the value from the original OCR record.
    Column name is retained as a compatibility fallback.
    """
    value_by_tag_id = {}
    value_by_column = {}

    for item in values:
        value = _safe_text(
            item.get(
                "value",
                "",
            ),
            MAX_SUMMARY_VALUE_LENGTH,
        )

        raw_tag_id = item.get(
            "tag_id"
        )

        try:
            tag_id = _positive_integer(
                raw_tag_id,
                "ocr_values.tag_id",
            )

        except SummaryValidationError:
            tag_id = None

        if tag_id is not None:
            # หากมีหลายค่า Tag เดียวกัน
            # รายการ ID ล่าสุดจะชนะ เนื่องจาก
            # Query เรียงตาม id จากน้อยไปมาก
            value_by_tag_id[
                tag_id
            ] = value

        try:
            column_name = (
                _summary_column_name(
                    item
                )
            )

        except SummaryValidationError:
            continue

        value_by_column[
            column_name
        ] = value

    return (
        value_by_tag_id,
        value_by_column,
    )


def _build_summary_row(
    run: dict[str, Any],
    values: list[
        dict[str, Any]
    ],
    tags: list[
        dict[str, Any]
    ],
) -> tuple[
    list[str],
    list[Any],
]:
    value_by_tag_id, value_by_column = (
        _build_value_maps(
            values
        )
    )

    columns = [
        "run_id",
        "ocr_status",
        "ocr_time",
    ]

    row_values = [
        _positive_integer(
            run.get(
                "id"
            ),
            "run.id",
        ),
        _safe_text(
            run.get(
                "status",
                "",
            ),
            50,
        ),
        _safe_text(
            (
                run.get(
                    "ocr_time"
                )
                or run.get(
                    "created_at"
                )
                or ""
            ),
            100,
        ),
    ]

    used_column_names = {
        column_name.casefold()
        for column_name in (
            *columns,
            "created_at",
        )
    }

    for tag in tags:
        column_name = (
            _summary_column_name(
                tag
            )
        )

        duplicate_key = (
            column_name.casefold()
        )

        if duplicate_key in used_column_names:
            raise SummaryValidationError(
                (
                    "Duplicate or reserved "
                    "Summary column name: "
                    f"{column_name}"
                )
            )

        used_column_names.add(
            duplicate_key
        )

        columns.append(
            column_name
        )

        try:
            tag_id = _positive_integer(
                tag.get(
                    "id"
                ),
                "user_tags.id",
            )

        except SummaryValidationError:
            tag_id = None

        if (
            tag_id is not None
            and tag_id
            in value_by_tag_id
        ):
            value = value_by_tag_id[
                tag_id
            ]

        else:
            value = value_by_column.get(
                column_name,
                "",
            )

        row_values.append(
            value
        )

    columns.append(
        "created_at"
    )

    row_values.append(
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    return (
        columns,
        row_values,
    )


def _validate_summary_table_schema(
    conn,
    table_name: str,
    expected_columns: list[str],
) -> None:
    quoted_table = (
        _quote_identifier(
            table_name
        )
    )

    schema_rows = conn.execute(
        f"""
        PRAGMA table_info(
            {quoted_table}
        )
        """
    ).fetchall()

    if not schema_rows:
        raise SummaryRepositoryError(
            (
                "Summary table does "
                "not exist"
            )
        )

    existing_columns = {
        str(
            row[1]
        ).casefold()
        for row in schema_rows
    }

    missing_columns = [
        column
        for column in expected_columns
        if column.casefold()
        not in existing_columns
    ]

    if missing_columns:
        raise SummaryRepositoryError(
            (
                "Summary table is missing "
                "required column(s): "
                + ", ".join(
                    missing_columns
                )
            )
        )


def _store_summary_row(
    table_name: str,
    columns: list[str],
    row_values: list[Any],
    run_id: int,
) -> None:
    if len(
        columns
    ) != len(
        row_values
    ):
        raise SummaryRepositoryError(
            (
                "Summary column and value "
                "counts do not match"
            )
        )

    quoted_table = (
        _quote_identifier(
            table_name
        )
    )

    quoted_columns = ", ".join(
        _quote_identifier(
            column_name
        )
        for column_name in columns
    )

    placeholders = ", ".join(
        "?"
        for _ in columns
    )

    conn = None

    try:
        conn = get_connection()

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        _validate_summary_table_schema(
            conn=conn,
            table_name=table_name,
            expected_columns=columns,
        )

        # DELETE และ INSERT อยู่ใน Transaction
        # เดียวกัน หาก INSERT ล้มเหลว Rollback
        # จะคืนแถวเดิมกลับมา
        conn.execute(
            f"""
            DELETE FROM {quoted_table}
            WHERE "run_id" = ?
            """,
            (
                run_id,
            ),
        )

        conn.execute(
            f"""
            INSERT INTO {quoted_table} (
                {quoted_columns}
            )
            VALUES (
                {placeholders}
            )
            """,
            row_values,
        )

        verification = conn.execute(
            f"""
            SELECT 1
            FROM {quoted_table}
            WHERE "run_id" = ?
            LIMIT 1
            """,
            (
                run_id,
            ),
        ).fetchone()

        if verification is None:
            raise SummaryRepositoryError(
                (
                    "Summary row could not "
                    "be verified after saving"
                )
            )

        conn.commit()

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Failed to store Summary "
                "row: run_id=%s, table=%s"
            ),
            run_id,
            table_name,
        )

        raise

    finally:
        _safe_close(
            conn
        )


def save_summary_row(
    run_id,
) -> bool:
    """
    Create or replace the Summary row for one OCR run.

    Calling this function repeatedly with the same run_id
    is safe and leaves one current Summary row.
    """
    normalized_run_id = (
        _positive_integer(
            run_id,
            "run_id",
        )
    )

    (
        run,
        values,
        tags,
    ) = _load_summary_data(
        normalized_run_id
    )

    if run is None:
        logger.warning(
            (
                "OCR run was not found "
                "for Summary: run_id=%s"
            ),
            normalized_run_id,
        )

        return False

    if not tags:
        logger.debug(
            (
                "Summary creation skipped "
                "because no active Tags "
                "exist: run_id=%s"
            ),
            normalized_run_id,
        )

        return False

    (
        columns,
        row_values,
    ) = _build_summary_row(
        run=run,
        values=values,
        tags=tags,
    )

    try:
        raw_table_name = (
            get_or_create_active_summary_table(
                tags
            )
        )

        table_name = (
            _validate_table_name(
                raw_table_name
            )
        )

    except Exception:
        logger.exception(
            (
                "Failed to prepare active "
                "Summary table: run_id=%s"
            ),
            normalized_run_id,
        )

        raise

    _store_summary_row(
        table_name=table_name,
        columns=columns,
        row_values=row_values,
        run_id=normalized_run_id,
    )

    logger.debug(
        (
            "Summary row saved: "
            "run_id=%s, table=%s"
        ),
        normalized_run_id,
        table_name,
    )

    return True