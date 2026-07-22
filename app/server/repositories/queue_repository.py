from datetime import datetime
from typing import Any

from app.server.database import get_connection


QUEUE_STATUS_PENDING = "PENDING"
QUEUE_STATUS_SENT = "SENT"


def create_queue_items(
    run_id: int,
    sensor_values: list[dict[str, Any]]
) -> list[int]:
    if not run_id:
        raise ValueError("run_id is required")

    if not isinstance(sensor_values, list):
        raise ValueError(
            "sensor_values must be a list"
        )

    if not sensor_values:
        return []

    conn = get_connection()
    cur = conn.cursor()

    queue_ids = []
    created_at = datetime.now().astimezone().isoformat()

    try:
        for index, item in enumerate(sensor_values):
            if not isinstance(item, dict):
                raise ValueError(
                    f"sensor_values[{index}] "
                    "must be an object"
                )

            tag_id = item.get("tag_id")

            tag_name = str(
                item.get("tag_name", "")
            ).strip()

            sensor_api_key = str(
                item.get("sensor_api_key", "")
            ).strip()

            capture_timestamp = item.get(
                "capture_timestamp"
            )

            value = item.get("value")

            if not tag_id:
                raise ValueError(
                    f"sensor_values[{index}].tag_id "
                    "is required"
                )

            if not tag_name:
                raise ValueError(
                    f"sensor_values[{index}].tag_name "
                    "is required"
                )

            if not sensor_api_key:
                raise ValueError(
                    f"sensor_values[{index}]."
                    "sensor_api_key is required"
                )

            try:
                timestamp_value = int(
                    capture_timestamp
                )
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"sensor_values[{index}]."
                    "capture_timestamp is invalid"
                ) from error

            try:
                numeric_value = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"sensor_values[{index}].value "
                    "is invalid"
                ) from error

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
                    int(run_id),
                    int(tag_id),
                    tag_name,
                    sensor_api_key,
                    timestamp_value,
                    numeric_value,
                    QUEUE_STATUS_PENDING,
                    0,
                    created_at
                )
            )

            queue_ids.append(cur.lastrowid)

        conn.commit()

        return queue_ids

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def get_pending_queue(
    limit: int = 100
) -> list[dict[str, Any]]:
    try:
        queue_limit = int(limit)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "limit must be an integer"
        ) from error

    if queue_limit <= 0:
        raise ValueError(
            "limit must be greater than zero"
        )

    conn = get_connection()
    cur = conn.cursor()

    try:
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
            ORDER BY capture_timestamp ASC, id ASC
            LIMIT ?
            """,
            (
                QUEUE_STATUS_PENDING,
                queue_limit
            )
        )

        rows = cur.fetchall()

        column_names = [
            column[0]
            for column in cur.description
        ]

        return [
            dict(
                zip(
                    column_names,
                    row
                )
            )
            for row in rows
        ]

    finally:
        conn.close()


def mark_queue_sent(
    queue_ids: list[int],
    http_status: int | None = None,
    response_message: str = ""
) -> int:
    normalized_ids = _normalize_queue_ids(
        queue_ids
    )

    if not normalized_ids:
        return 0

    conn = get_connection()
    cur = conn.cursor()

    placeholders = ",".join(
        "?"
        for _ in normalized_ids
    )

    sent_at = (
        datetime.now()
        .astimezone()
        .isoformat()
    )

    try:
        cur.execute(
            f"""
            UPDATE outbound_sensor_queue
            SET
                status = ?,
                http_status = ?,
                response_message = ?,
                last_error = NULL,
                sent_at = ?
            WHERE id IN ({placeholders})
            """,
            (
                QUEUE_STATUS_SENT,
                http_status,
                str(response_message),
                sent_at,
                *normalized_ids
            )
        )

        updated_count = cur.rowcount

        conn.commit()

        return updated_count

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def mark_queue_failed(
    queue_ids: list[int],
    error_message: str,
    http_status: int | None = None,
    response_message: str = ""
) -> int:
    normalized_ids = _normalize_queue_ids(
        queue_ids
    )

    if not normalized_ids:
        return 0

    conn = get_connection()
    cur = conn.cursor()

    placeholders = ",".join(
        "?"
        for _ in normalized_ids
    )

    last_attempt_at = (
        datetime.now()
        .astimezone()
        .isoformat()
    )

    try:
        cur.execute(
            f"""
            UPDATE outbound_sensor_queue
            SET
                status = ?,
                retry_count = retry_count + 1,
                http_status = ?,
                response_message = ?,
                last_error = ?,
                last_attempt_at = ?
            WHERE id IN ({placeholders})
            """,
            (
                QUEUE_STATUS_PENDING,
                http_status,
                str(response_message),
                str(error_message),
                last_attempt_at,
                *normalized_ids
            )
        )

        updated_count = cur.rowcount

        conn.commit()

        return updated_count

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def claim_pending_queue(
    limit: int = 100
) -> list[dict[str, Any]]:
    return get_pending_queue(limit)

    
def _normalize_queue_ids(
    queue_ids: list[int]
) -> list[int]:
    if not isinstance(queue_ids, list):
        raise ValueError(
            "queue_ids must be a list"
        )

    normalized_ids = []

    for queue_id in queue_ids:
        try:
            normalized_id = int(queue_id)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "queue_ids contains an invalid ID"
            ) from error

        if normalized_id <= 0:
            raise ValueError(
                "queue ID must be greater than zero"
            )

        if normalized_id not in normalized_ids:
            normalized_ids.append(
                normalized_id
            )

    return normalized_ids