import sqlite3
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from src.logger import create_logger
from src.server.database import (
    get_connection,
    to_relative_path,
)
from src.server.repositories.summary_repository import (
    save_summary_row,
)


logger = create_logger(
    "server.repositories.ocr"
)


VALID_RUN_STATUSES = {
    "NORMAL",
    "ALERT",
}

MAX_PATH_LENGTH = 2048
MAX_TAG_NAME_LENGTH = 150
MAX_UNIT_LENGTH = 100
MAX_VALUE_LENGTH = 500
MAX_RAW_TEXT_LENGTH = 2000
MAX_ALERT_MESSAGE_LENGTH = 2000
MAX_MISSING_TAGS = 1000
MAX_RESULTS = 5000


class OCRRepositoryValidationError(
    ValueError
):
    """
    Raised when OCR run data is invalid.
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
                "OCR database transaction"
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
                "Failed to close OCR "
                "database connection"
            )
        )


def _required_text(
    value: Any,
    field_name: str,
    max_length: int,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise OCRRepositoryValidationError(
            (
                f"{field_name} must "
                "be a string"
            )
        )

    normalized = value.strip()

    if not normalized:
        raise OCRRepositoryValidationError(
            f"{field_name} is required"
        )

    if "\x00" in normalized:
        raise OCRRepositoryValidationError(
            (
                f"{field_name} contains "
                "an invalid character"
            )
        )

    if len(
        normalized
    ) > max_length:
        raise OCRRepositoryValidationError(
            f"{field_name} is too long"
        )

    return normalized


def _optional_text(
    value: Any,
    field_name: str,
    max_length: int,
) -> str:
    if value is None:
        return ""

    try:
        normalized = str(
            value
        ).strip()

    except Exception as error:
        raise OCRRepositoryValidationError(
            (
                f"{field_name} cannot "
                "be converted to text"
            )
        ) from error

    if "\x00" in normalized:
        raise OCRRepositoryValidationError(
            (
                f"{field_name} contains "
                "an invalid character"
            )
        )

    if len(
        normalized
    ) > max_length:
        normalized = normalized[
            :max_length
        ]

    return normalized


def _positive_integer(
    value: Any,
    field_name: str,
) -> int:
    if isinstance(
        value,
        bool,
    ):
        raise OCRRepositoryValidationError(
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
        raise OCRRepositoryValidationError(
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
        raise OCRRepositoryValidationError(
            (
                f"{field_name} must "
                "be an integer"
            )
        ) from error

    if parsed <= 0:
        raise OCRRepositoryValidationError(
            (
                f"{field_name} must be "
                "greater than zero"
            )
        )

    return parsed


def _normalize_status(
    value: Any,
) -> str:
    status = _required_text(
        value,
        "status",
        20,
    ).upper()

    if status not in VALID_RUN_STATUSES:
        raise OCRRepositoryValidationError(
            (
                "status must be "
                "NORMAL or ALERT"
            )
        )

    return status


def _normalize_path(
    value: Any,
    field_name: str,
) -> str:
    path_text = _required_text(
        value,
        field_name,
        MAX_PATH_LENGTH,
    )

    try:
        relative_path = (
            to_relative_path(
                path_text
            )
        )

    except Exception as error:
        raise OCRRepositoryValidationError(
            (
                f"{field_name} cannot "
                "be converted to a "
                "relative path"
            )
        ) from error

    relative_text = str(
        relative_path
    ).strip()

    if not relative_text:
        raise OCRRepositoryValidationError(
            (
                f"{field_name} produced "
                "an empty relative path"
            )
        )

    if len(
        relative_text
    ) > MAX_PATH_LENGTH:
        raise OCRRepositoryValidationError(
            f"{field_name} is too long"
        )

    return relative_text


def _normalize_captured_at(
    value: Any,
) -> str:
    captured_at_text = _required_text(
        value,
        "captured_at",
        100,
    )

    parse_text = captured_at_text

    if parse_text.endswith(
        "Z"
    ):
        parse_text = (
            parse_text[:-1]
            + "+00:00"
        )

    try:
        captured_at = (
            datetime.fromisoformat(
                parse_text
            )
        )

    except ValueError as error:
        raise OCRRepositoryValidationError(
            (
                "captured_at must be a "
                "valid ISO 8601 datetime"
            )
        ) from error

    if captured_at.tzinfo is None:
        raise OCRRepositoryValidationError(
            (
                "captured_at must include "
                "a timezone offset"
            )
        )

    return captured_at.isoformat()


def _normalize_missing_tags(
    missing_tags: Any,
) -> list[str]:
    if missing_tags is None:
        return []

    if not isinstance(
        missing_tags,
        list,
    ):
        raise OCRRepositoryValidationError(
            (
                "missing_tags must "
                "be a list"
            )
        )

    if len(
        missing_tags
    ) > MAX_MISSING_TAGS:
        raise OCRRepositoryValidationError(
            (
                "missing_tags contains "
                "too many items"
            )
        )

    normalized_tags = []
    seen_tags = set()

    for index, tag_name in enumerate(
        missing_tags
    ):
        normalized_name = (
            _required_text(
                tag_name,
                (
                    f"missing_tags["
                    f"{index}]"
                ),
                MAX_TAG_NAME_LENGTH,
            )
        )

        duplicate_key = (
            normalized_name.casefold()
        )

        if duplicate_key in seen_tags:
            continue

        seen_tags.add(
            duplicate_key
        )

        normalized_tags.append(
            normalized_name
        )

    return normalized_tags


def _normalize_tag(
    tag: Any,
    field_prefix: str,
) -> dict[str, Any]:
    if not isinstance(
        tag,
        Mapping,
    ):
        raise OCRRepositoryValidationError(
            (
                f"{field_prefix} must "
                "be an object"
            )
        )

    tag_id = _positive_integer(
        tag.get(
            "id"
        ),
        f"{field_prefix}.id",
    )

    tag_name = _required_text(
        tag.get(
            "tag_name"
        ),
        f"{field_prefix}.tag_name",
        MAX_TAG_NAME_LENGTH,
    )

    unit = _optional_text(
        tag.get(
            "unit",
            "",
        ),
        f"{field_prefix}.unit",
        MAX_UNIT_LENGTH,
    )

    return {
        "id": tag_id,
        "tag_name": tag_name,
        "unit": unit,
    }


def _normalize_results(
    results: Any,
) -> list[dict[str, Any]]:
    if not isinstance(
        results,
        list,
    ):
        raise OCRRepositoryValidationError(
            "results must be a list"
        )

    if not results:
        raise OCRRepositoryValidationError(
            (
                "results must contain "
                "at least one item"
            )
        )

    if len(
        results
    ) > MAX_RESULTS:
        raise OCRRepositoryValidationError(
            (
                "results contains too "
                "many items"
            )
        )

    normalized_results = []

    for index, item in enumerate(
        results
    ):
        if not isinstance(
            item,
            Mapping,
        ):
            raise OCRRepositoryValidationError(
                (
                    f"results[{index}] "
                    "must be an object"
                )
            )

        tag = _normalize_tag(
            item.get(
                "tag"
            ),
            f"results[{index}].tag",
        )

        value = _optional_text(
            item.get(
                "value",
                "",
            ),
            f"results[{index}].value",
            MAX_VALUE_LENGTH,
        )

        raw_text = _optional_text(
            item.get(
                "raw_text",
                "",
            ),
            f"results[{index}].raw_text",
            MAX_RAW_TEXT_LENGTH,
        )

        normalized_results.append({
            "tag": tag,
            "value": value,
            "raw_text": raw_text,
        })

    return normalized_results


def _database_now() -> str:
    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _create_summary_safely(
    run_id: int,
) -> bool:
    """
    Summary generation occurs after the OCR transaction.

    A summary failure must not make the API report that
    the already-committed OCR run failed, because that
    could cause the Worker to submit the same run again.
    """
    try:
        save_summary_row(
            run_id=run_id
        )

    except Exception:
        logger.exception(
            (
                "OCR run %s was saved, "
                "but its summary row "
                "could not be created"
            ),
            run_id,
        )

        return False

    logger.info(
        (
            "Summary row created "
            "for OCR run %s"
        ),
        run_id,
    )

    return True


def create_ocr_run(
    raw_image_path,
    calibrated_image_path,
    status,
    missing_tags,
    alert_message,
):
    normalized_raw_path = (
        _normalize_path(
            raw_image_path,
            "raw_image_path",
        )
    )

    normalized_calibrated_path = (
        _normalize_path(
            calibrated_image_path,
            "calibrated_image_path",
        )
    )

    normalized_status = (
        _normalize_status(
            status
        )
    )

    normalized_missing_tags = (
        _normalize_missing_tags(
            missing_tags
        )
    )

    normalized_alert_message = (
        _optional_text(
            alert_message,
            "alert_message",
            MAX_ALERT_MESSAGE_LENGTH,
        )
    )

    now = _database_now()
    conn = None

    try:
        conn = get_connection()

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        cursor = conn.execute(
            """
            INSERT INTO ocr_runs (
                raw_image_path,
                calibrated_image_path,
                ocr_time,
                status,
                missing_tags,
                alert_message,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_raw_path,
                normalized_calibrated_path,
                now,
                normalized_status,
                ",".join(
                    normalized_missing_tags
                ),
                normalized_alert_message,
                now,
            ),
        )

        run_id = cursor.lastrowid

        if run_id is None:
            raise RuntimeError(
                (
                    "Database did not return "
                    "the OCR run id"
                )
            )

        conn.commit()

        logger.info(
            (
                "OCR run created: "
                "run_id=%s, status=%s"
            ),
            run_id,
            normalized_status,
        )

        return int(
            run_id
        )

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            "Failed to create OCR run"
        )

        raise

    finally:
        _safe_close(
            conn
        )


def save_ocr_value(
    run_id,
    tag,
    value,
    raw_text,
):
    normalized_run_id = (
        _positive_integer(
            run_id,
            "run_id",
        )
    )

    normalized_tag = (
        _normalize_tag(
            tag,
            "tag",
        )
    )

    normalized_value = _optional_text(
        value,
        "value",
        MAX_VALUE_LENGTH,
    )

    normalized_raw_text = (
        _optional_text(
            raw_text,
            "raw_text",
            MAX_RAW_TEXT_LENGTH,
        )
    )

    now = _database_now()
    conn = None

    try:
        conn = get_connection()

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        conn.execute(
            """
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
            """,
            (
                normalized_run_id,
                normalized_tag["id"],
                normalized_tag[
                    "tag_name"
                ],
                normalized_tag["unit"],
                normalized_value,
                normalized_raw_text,
                now,
            ),
        )

        conn.commit()

        logger.debug(
            (
                "OCR value saved: "
                "run_id=%s, tag_id=%s"
            ),
            normalized_run_id,
            normalized_tag["id"],
        )

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Failed to save OCR value: "
                "run_id=%s"
            ),
            normalized_run_id,
        )

        raise

    finally:
        _safe_close(
            conn
        )


def save_worker_ocr_run(
    raw_image_path,
    calibrated_image_path,
    results,
    status,
    missing_tags,
    alert_message,
    captured_at,
):
    """
    Save one OCR run and all of its values within
    a single database transaction.

    Summary creation is deliberately isolated from
    the OCR transaction. If summary creation fails,
    the committed OCR run remains successful so the
    Worker does not retry and create a duplicate run.
    """
    normalized_raw_path = (
        _normalize_path(
            raw_image_path,
            "raw_image_path",
        )
    )

    normalized_calibrated_path = (
        _normalize_path(
            calibrated_image_path,
            "calibrated_image_path",
        )
    )

    normalized_results = (
        _normalize_results(
            results
        )
    )

    normalized_status = (
        _normalize_status(
            status
        )
    )

    normalized_missing_tags = (
        _normalize_missing_tags(
            missing_tags
        )
    )

    normalized_alert_message = (
        _optional_text(
            alert_message,
            "alert_message",
            MAX_ALERT_MESSAGE_LENGTH,
        )
    )

    normalized_captured_at = (
        _normalize_captured_at(
            captured_at
        )
    )

    now = _database_now()
    conn = None
    run_id = None

    try:
        conn = get_connection()

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        cursor = conn.execute(
            """
            INSERT INTO ocr_runs (
                raw_image_path,
                calibrated_image_path,
                ocr_time,
                status,
                missing_tags,
                alert_message,
                captured_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_raw_path,
                normalized_calibrated_path,
                now,
                normalized_status,
                ",".join(
                    normalized_missing_tags
                ),
                normalized_alert_message,
                normalized_captured_at,
                now,
            ),
        )

        run_id = cursor.lastrowid

        if run_id is None:
            raise RuntimeError(
                (
                    "Database did not return "
                    "the OCR run id"
                )
            )

        value_rows = []

        for item in normalized_results:
            tag = item[
                "tag"
            ]

            value_rows.append((
                int(
                    run_id
                ),
                tag["id"],
                tag["tag_name"],
                tag["unit"],
                item["value"],
                item["raw_text"],
                now,
            ))

        conn.executemany(
            """
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
            """,
            value_rows,
        )

        conn.commit()

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Failed to save Worker "
                "OCR run"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )

    run_id = int(
        run_id
    )

    logger.info(
        (
            "Worker OCR run saved: "
            "run_id=%s, status=%s, "
            "value_count=%d"
        ),
        run_id,
        normalized_status,
        len(
            normalized_results
        ),
    )

    _create_summary_safely(
        run_id
    )

    return run_id