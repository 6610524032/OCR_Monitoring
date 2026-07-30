import math
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from src.logger import create_logger
from src.server.database import get_connection


logger = create_logger(
    "server.repositories.queue"
)


QUEUE_STATUS_PENDING = "PENDING"
QUEUE_STATUS_SENT = "SENT"

DEFAULT_QUEUE_LIMIT = 100
MAX_QUEUE_LIMIT = 1000
MAX_MESSAGE_LENGTH = 2000


def _now_iso() -> str:
    return (
        datetime.now()
        .astimezone()
        .isoformat()
    )


def _safe_close(conn) -> None:
    """
    Close the database connection safely.

    A connection close error must not hide
    the original database error.
    """
    if conn is None:
        return

    try:
        conn.close()

    except Exception:
        logger.exception(
            "Failed to close queue database connection"
        )


def _safe_rollback(conn) -> None:
    """
    Roll back a database transaction safely.
    """
    if conn is None:
        return

    try:
        conn.rollback()

    except Exception:
        logger.exception(
            "Failed to roll back queue transaction"
        )


def _safe_text(
    value: Any,
) -> str:
    """
    Limit stored error and response messages
    so the database does not receive huge data.
    """
    return str(
        value or ""
    )[
        :MAX_MESSAGE_LENGTH
    ]


def _positive_int(
    value: Any,
    field_name: str,
) -> int:
    try:
        normalized = int(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise ValueError(
            f"{field_name} must be an integer"
        ) from error

    if normalized <= 0:
        raise ValueError(
            (
                f"{field_name} must be "
                "greater than zero"
            )
        )

    return normalized


def _normalize_http_status(
    http_status: Any,
) -> int | None:
    if http_status is None:
        return None

    try:
        normalized = int(
            http_status
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise ValueError(
            "http_status must be an integer"
        ) from error

    if not (
        100 <= normalized <= 599
    ):
        raise ValueError(
            (
                "http_status must be "
                "between 100 and 599"
            )
        )

    return normalized


def _normalize_limit(
    limit: Any,
) -> int:
    try:
        normalized = int(
            limit
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise ValueError(
            "limit must be an integer"
        ) from error

    if normalized <= 0:
        raise ValueError(
            "limit must be greater than zero"
        )

    if normalized > MAX_QUEUE_LIMIT:
        logger.warning(
            (
                "Queue limit %d exceeds "
                "maximum; using %d"
            ),
            normalized,
            MAX_QUEUE_LIMIT,
        )

        normalized = (
            MAX_QUEUE_LIMIT
        )

    return normalized


def _normalize_queue_ids(
    queue_ids: list[int],
) -> list[int]:
    if not isinstance(
        queue_ids,
        list,
    ):
        raise ValueError(
            "queue_ids must be a list"
        )

    normalized_ids = []
    seen_ids = set()

    for index, queue_id in enumerate(
        queue_ids
    ):
        normalized_id = (
            _positive_int(
                queue_id,
                f"queue_ids[{index}]",
            )
        )

        if normalized_id in seen_ids:
            continue

        seen_ids.add(
            normalized_id
        )

        normalized_ids.append(
            normalized_id
        )

    return normalized_ids


def _normalize_sensor_item(
    item: Any,
    index: int,
) -> dict[str, Any]:
    prefix = (
        f"sensor_values[{index}]"
    )

    if not isinstance(
        item,
        Mapping,
    ):
        raise ValueError(
            f"{prefix} must be an object"
        )

    tag_id = _positive_int(
        item.get(
            "tag_id"
        ),
        f"{prefix}.tag_id",
    )

    tag_name = str(
        item.get(
            "tag_name",
            "",
        )
    ).strip()

    sensor_api_key = str(
        item.get(
            "sensor_api_key",
            "",
        )
    ).strip()

    if not tag_name:
        raise ValueError(
            (
                f"{prefix}."
                "tag_name is required"
            )
        )

    if not sensor_api_key:
        raise ValueError(
            (
                f"{prefix}."
                "sensor_api_key is required"
            )
        )

    try:
        capture_timestamp = int(
            item.get(
                "capture_timestamp"
            )
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise ValueError(
            (
                f"{prefix}."
                "capture_timestamp is invalid"
            )
        ) from error

    if capture_timestamp < 0:
        raise ValueError(
            (
                f"{prefix}."
                "capture_timestamp cannot "
                "be negative"
            )
        )

    try:
        numeric_value = float(
            item.get(
                "value"
            )
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise ValueError(
            (
                f"{prefix}."
                "value is invalid"
            )
        ) from error

    if not math.isfinite(
        numeric_value
    ):
        raise ValueError(
            (
                f"{prefix}."
                "value must be finite"
            )
        )

    return {
        "tag_id": tag_id,
        "tag_name": tag_name,
        "sensor_api_key": (
            sensor_api_key
        ),
        "capture_timestamp": (
            capture_timestamp
        ),
        "value": numeric_value,
    }


def create_queue_items(
    run_id: int,
    sensor_values: list[dict[str, Any]],
) -> list[int]:
    try:
        normalized_run_id = (
            _positive_int(
                run_id,
                "run_id",
            )
        )

        if not isinstance(
            sensor_values,
            list,
        ):
            raise ValueError(
                (
                    "sensor_values must "
                    "be a list"
                )
            )

        if not sensor_values:
            logger.debug(
                (
                    "No sensor values "
                    "provided for queue"
                )
            )

            return []

        normalized_items = [
            _normalize_sensor_item(
                item,
                index,
            )
            for index, item in enumerate(
                sensor_values
            )
        ]

    except ValueError as error:
        logger.error(
            (
                "Invalid outbound queue "
                "data: %s"
            ),
            error,
        )

        raise

    conn = None
    queue_ids = []

    created_at = (
        _now_iso()
    )

    try:
        conn = get_connection()
        cur = conn.cursor()

        for item in normalized_items:
            cur.execute(
                """
                INSERT INTO outbound_sensor_queue (
                    run_id,
                    tag_id,
                    tag_name,
                    sensor_api_key,
                    capture_timestamp,
                    value,
                    status,
                    retry_count,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_run_id,
                    item["tag_id"],
                    item["tag_name"],
                    item["sensor_api_key"],
                    item["capture_timestamp"],
                    item["value"],
                    QUEUE_STATUS_PENDING,
                    0,
                    created_at,
                ),
            )

            queue_ids.append(
                int(
                    cur.lastrowid
                )
            )

        conn.commit()

        logger.info(
            (
                "Created %d outbound "
                "queue item(s) for run %d"
            ),
            len(queue_ids),
            normalized_run_id,
        )

        return queue_ids

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Failed to create "
                "outbound queue items"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )


def get_pending_queue(
    limit: int = DEFAULT_QUEUE_LIMIT,
) -> list[dict[str, Any]]:
    try:
        queue_limit = (
            _normalize_limit(
                limit
            )
        )

    except ValueError as error:
        logger.error(
            (
                "Invalid pending queue "
                "limit: %s"
            ),
            error,
        )

        raise

    conn = None

    try:
        conn = get_connection()
        conn.row_factory = (
            sqlite3.Row
        )

        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                id,
                run_id,
                tag_id,
                tag_name,
                sensor_api_key,
                capture_timestamp,
                value,
                status,
                retry_count,
                http_status,
                response_message,
                last_error,
                created_at,
                last_attempt_at,
                sent_at
            FROM outbound_sensor_queue
            WHERE status = ?
            ORDER BY
                capture_timestamp ASC,
                id ASC
            LIMIT ?
            """,
            (
                QUEUE_STATUS_PENDING,
                queue_limit,
            ),
        )

        queue_items = [
            dict(
                row
            )
            for row in cur.fetchall()
        ]

        if queue_items:
            logger.info(
                (
                    "Loaded %d pending "
                    "queue item(s)"
                ),
                len(queue_items),
            )

        return queue_items

    except Exception:
        logger.exception(
            "Failed to load pending queue"
        )

        raise

    finally:
        _safe_close(
            conn
        )


def mark_queue_sent(
    queue_ids: list[int],
    http_status: int | None = None,
    response_message: str = "",
) -> int:
    try:
        normalized_ids = (
            _normalize_queue_ids(
                queue_ids
            )
        )

        normalized_status = (
            _normalize_http_status(
                http_status
            )
        )

    except ValueError as error:
        logger.error(
            (
                "Invalid mark-sent "
                "data: %s"
            ),
            error,
        )

        raise

    if not normalized_ids:
        logger.debug(
            (
                "No queue items to "
                "mark as sent"
            )
        )

        return 0

    placeholders = ",".join(
        "?"
        for _ in normalized_ids
    )

    sent_at = (
        _now_iso()
    )

    conn = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            f"""
            UPDATE outbound_sensor_queue
            SET
                status = ?,
                http_status = ?,
                response_message = ?,
                last_error = NULL,
                last_attempt_at = ?,
                sent_at = ?
            WHERE id IN ({placeholders})
              AND status != ?
            """,
            (
                QUEUE_STATUS_SENT,
                normalized_status,
                _safe_text(
                    response_message
                ),
                sent_at,
                sent_at,
                *normalized_ids,
                QUEUE_STATUS_SENT,
            ),
        )

        updated_count = (
            cur.rowcount
        )

        conn.commit()

        logger.info(
            (
                "Marked %d queue "
                "item(s) as sent"
            ),
            updated_count,
        )

        return updated_count

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            "Failed to mark queue as sent"
        )

        raise

    finally:
        _safe_close(
            conn
        )


def mark_queue_failed(
    queue_ids: list[int],
    error_message: str,
    http_status: int | None = None,
    response_message: str = "",
) -> int:
    try:
        normalized_ids = (
            _normalize_queue_ids(
                queue_ids
            )
        )

        normalized_status = (
            _normalize_http_status(
                http_status
            )
        )

    except ValueError as error:
        logger.error(
            (
                "Invalid mark-failed "
                "data: %s"
            ),
            error,
        )

        raise

    if not normalized_ids:
        logger.debug(
            (
                "No queue items to "
                "mark as failed"
            )
        )

        return 0

    normalized_error = (
        _safe_text(
            error_message
        )
    )

    if not normalized_error:
        normalized_error = (
            "Unknown outbound queue error"
        )

    placeholders = ",".join(
        "?"
        for _ in normalized_ids
    )

    last_attempt_at = (
        _now_iso()
    )

    conn = None

    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute(
            f"""
            UPDATE outbound_sensor_queue
            SET
                status = ?,
                retry_count =
                    COALESCE(retry_count, 0) + 1,
                http_status = ?,
                response_message = ?,
                last_error = ?,
                last_attempt_at = ?
            WHERE id IN ({placeholders})
              AND status != ?
            """,
            (
                QUEUE_STATUS_PENDING,
                normalized_status,
                _safe_text(
                    response_message
                ),
                normalized_error,
                last_attempt_at,
                *normalized_ids,
                QUEUE_STATUS_SENT,
            ),
        )

        updated_count = (
            cur.rowcount
        )

        conn.commit()

        logger.warning(
            (
                "Marked %d queue "
                "item(s) for retry"
            ),
            updated_count,
        )

        return updated_count

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            "Failed to mark queue as failed"
        )

        raise

    finally:
        _safe_close(
            conn
        )


def claim_pending_queue(
    limit: int = DEFAULT_QUEUE_LIMIT,
) -> list[dict[str, Any]]:
    queue_limit = (
        _normalize_limit(
            limit
        )
    )

    # ใช้ DEBUG เพื่อไม่ให้ Log ถูกเขียนซ้ำ
    # ทุก 5 วินาทีเมื่อคิวว่าง
    logger.debug(
        (
            "Claiming pending queue "
            "(limit=%d)"
        ),
        queue_limit,
    )

    return get_pending_queue(
        queue_limit
    )