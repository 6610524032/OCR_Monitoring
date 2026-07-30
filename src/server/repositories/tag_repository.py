import math
import sqlite3
from collections.abc import Mapping
from typing import Any

from src.logger import create_logger
from src.server.database import get_connection


logger = create_logger(
    "server.repositories.tag"
)


DEFAULT_OUTPUT_WIDTH = 900
DEFAULT_OUTPUT_HEIGHT = 700

MAX_TAG_COUNT = 500
MAX_TAG_NAME_LENGTH = 150
MAX_UNIT_LENGTH = 100
MAX_SENSOR_API_KEY_LENGTH = 500
MAX_ROI_COORDINATE = 1_000_000.0

ROI_BOUND_EPSILON = 1e-6


class TagValidationError(
    ValueError
):
    """
    Raised when user-tag or ROI
    input is invalid.
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
                "user-tag transaction"
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
                "Failed to close user-tag "
                "database connection"
            )
        )


def _normalize_text(
    value: Any,
    field_name: str,
    max_length: int,
    required: bool = False,
) -> str:
    if value is None:
        normalized = ""

    elif isinstance(
        value,
        str,
    ):
        normalized = value.strip()

    else:
        raise TagValidationError(
            f"{field_name} must be a string"
        )

    if (
        required
        and not normalized
    ):
        raise TagValidationError(
            f"{field_name} is required"
        )

    if "\x00" in normalized:
        raise TagValidationError(
            (
                f"{field_name} contains "
                "an invalid character"
            )
        )

    if len(
        normalized
    ) > max_length:
        raise TagValidationError(
            (
                f"{field_name} exceeds "
                f"{max_length} characters"
            )
        )

    return normalized


def _parse_optional_id(
    value: Any,
    tag_number: int,
) -> int | None:
    if value in (
        None,
        "",
    ):
        return None

    if isinstance(
        value,
        bool,
    ):
        raise TagValidationError(
            (
                f"Tag number {tag_number} "
                "has an invalid id"
            )
        )

    if (
        isinstance(
            value,
            float,
        )
        and not value.is_integer()
    ):
        raise TagValidationError(
            (
                f"Tag number {tag_number} "
                "has an invalid id"
            )
        )

    try:
        tag_id = int(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise TagValidationError(
            (
                f"Tag number {tag_number} "
                "has an invalid id"
            )
        ) from error

    if tag_id <= 0:
        raise TagValidationError(
            (
                f"Tag number {tag_number} "
                "has an invalid id"
            )
        )

    return tag_id


def _finite_coordinate(
    value: Any,
    field_name: str,
) -> float:
    if isinstance(
        value,
        bool,
    ):
        raise TagValidationError(
            f"{field_name} must be numeric"
        )

    try:
        coordinate = float(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise TagValidationError(
            f"{field_name} must be numeric"
        ) from error

    if not math.isfinite(
        coordinate
    ):
        raise TagValidationError(
            f"{field_name} must be finite"
        )

    if coordinate < 0:
        raise TagValidationError(
            f"{field_name} cannot be negative"
        )

    if (
        coordinate
        > MAX_ROI_COORDINATE
    ):
        raise TagValidationError(
            f"{field_name} is too large"
        )

    return coordinate


def _validate_tags_payload(
    tags: Any,
) -> list[dict[str, Any]]:
    if not isinstance(
        tags,
        list,
    ):
        raise TagValidationError(
            "Tags must be a list"
        )

    if len(
        tags
    ) > MAX_TAG_COUNT:
        raise TagValidationError(
            (
                "Too many tags. "
                f"The maximum is "
                f"{MAX_TAG_COUNT}."
            )
        )

    validated_tags = []

    used_ids = set()
    used_names = set()
    used_sensor_keys = set()

    for index, raw_tag in enumerate(
        tags,
        start=1,
    ):
        if not isinstance(
            raw_tag,
            Mapping,
        ):
            raise TagValidationError(
                (
                    f"Tag number {index} "
                    "must be an object"
                )
            )

        tag_name = _normalize_text(
            value=raw_tag.get(
                "tag_name",
                raw_tag.get(
                    "display_name"
                ),
            ),
            field_name=(
                f"Tag number {index} name"
            ),
            max_length=(
                MAX_TAG_NAME_LENGTH
            ),
            required=True,
        )

        unit = _normalize_text(
            value=raw_tag.get(
                "unit",
                "",
            ),
            field_name=(
                f"Tag number {index} unit"
            ),
            max_length=(
                MAX_UNIT_LENGTH
            ),
        )

        sensor_api_key = (
            _normalize_text(
                value=raw_tag.get(
                    "sensor_api_key",
                    "",
                ),
                field_name=(
                    f"Tag number {index} "
                    "sensor API key"
                ),
                max_length=(
                    MAX_SENSOR_API_KEY_LENGTH
                ),
            )
        )

        tag_id = _parse_optional_id(
            raw_tag.get(
                "id"
            ),
            index,
        )

        if tag_id is not None:
            if tag_id in used_ids:
                raise TagValidationError(
                    (
                        f"Tag id {tag_id} "
                        "appears more than once"
                    )
                )

            used_ids.add(
                tag_id
            )

        normalized_name = (
            tag_name.casefold()
        )

        if normalized_name in used_names:
            raise TagValidationError(
                (
                    f"Duplicate tag name: "
                    f"{tag_name}"
                )
            )

        used_names.add(
            normalized_name
        )

        if sensor_api_key:
            if (
                sensor_api_key
                in used_sensor_keys
            ):
                raise TagValidationError(
                    (
                        "The same sensor API "
                        "key cannot be assigned "
                        "to multiple tags"
                    )
                )

            used_sensor_keys.add(
                sensor_api_key
            )

        x1 = _finite_coordinate(
            raw_tag.get(
                "x1"
            ),
            (
                f"Tag number {index} x1"
            ),
        )

        y1 = _finite_coordinate(
            raw_tag.get(
                "y1"
            ),
            (
                f"Tag number {index} y1"
            ),
        )

        x2 = _finite_coordinate(
            raw_tag.get(
                "x2"
            ),
            (
                f"Tag number {index} x2"
            ),
        )

        y2 = _finite_coordinate(
            raw_tag.get(
                "y2"
            ),
            (
                f"Tag number {index} y2"
            ),
        )

        if x2 <= x1:
            raise TagValidationError(
                (
                    f"Tag number {index} "
                    "must have x2 greater "
                    "than x1"
                )
            )

        if y2 <= y1:
            raise TagValidationError(
                (
                    f"Tag number {index} "
                    "must have y2 greater "
                    "than y1"
                )
            )

        validated_tags.append({
            "id": tag_id,
            "tag_name": tag_name,
            "unit": unit,
            "sensor_api_key": (
                sensor_api_key
            ),
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "display_order": index,
        })

    return validated_tags


def _load_calibration_bounds(
    conn,
) -> tuple[int, int] | None:
    row = conn.execute("""
        SELECT
            output_width,
            output_height
        FROM calibration
        WHERE is_active = 1
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    if row is None:
        return None

    raw_width = (
        row["output_width"]
        or DEFAULT_OUTPUT_WIDTH
    )

    raw_height = (
        row["output_height"]
        or DEFAULT_OUTPUT_HEIGHT
    )

    try:
        output_width = int(
            raw_width
        )

        output_height = int(
            raw_height
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise RuntimeError(
            (
                "Active calibration has "
                "invalid output dimensions"
            )
        ) from error

    if (
        output_width <= 0
        or output_height <= 0
    ):
        raise RuntimeError(
            (
                "Active calibration has "
                "invalid output dimensions"
            )
        )

    return (
        output_width,
        output_height,
    )


def _validate_roi_bounds(
    tags: list[dict[str, Any]],
    bounds: tuple[int, int] | None,
) -> None:
    if bounds is None:
        logger.debug(
            (
                "ROI upper-bound validation "
                "was skipped because no active "
                "calibration exists"
            )
        )

        return

    output_width, output_height = (
        bounds
    )

    for index, tag in enumerate(
        tags,
        start=1,
    ):
        if (
            tag["x2"]
            > (
                output_width
                + ROI_BOUND_EPSILON
            )
        ):
            raise TagValidationError(
                (
                    f"Tag number {index} ROI "
                    f"exceeds image width "
                    f"{output_width}"
                )
            )

        if (
            tag["y2"]
            > (
                output_height
                + ROI_BOUND_EPSILON
            )
        ):
            raise TagValidationError(
                (
                    f"Tag number {index} ROI "
                    f"exceeds image height "
                    f"{output_height}"
                )
            )


def _validate_existing_ids(
    conn,
    tags: list[dict[str, Any]],
) -> None:
    tag_ids = [
        tag["id"]
        for tag in tags
        if tag["id"] is not None
    ]

    if not tag_ids:
        return

    placeholders = ", ".join(
        ["?"] * len(
            tag_ids
        )
    )

    rows = conn.execute(
        f"""
        SELECT id
        FROM user_tags
        WHERE id IN (
            {placeholders}
        )
        """,
        tag_ids,
    ).fetchall()

    existing_ids = {
        int(
            row["id"]
        )
        for row in rows
    }

    missing_ids = [
        tag_id
        for tag_id in tag_ids
        if tag_id not in existing_ids
    ]

    if missing_ids:
        missing_text = ", ".join(
            str(
                tag_id
            )
            for tag_id in missing_ids
        )

        raise TagValidationError(
            (
                "The following tag id(s) "
                "were not found: "
                + missing_text
            )
        )


def _fetch_active_user_tags(
    conn,
    for_settings: bool,
) -> list[dict[str, Any]]:
    if for_settings:
        rows = conn.execute("""
            SELECT
                id,
                tag_name,
                tag_name AS display_name,
                unit,
                sensor_api_key,
                roi_x1 AS x1,
                roi_y1 AS y1,
                roi_x2 AS x2,
                roi_y2 AS y2,
                display_order,
                is_active
            FROM user_tags
            WHERE is_active = 1
            ORDER BY
                display_order ASC,
                id ASC
        """).fetchall()

    else:
        rows = conn.execute("""
            SELECT
                id,
                tag_name,
                unit,
                sensor_api_key,
                roi_x1,
                roi_y1,
                roi_x2,
                roi_y2,
                display_order
            FROM user_tags
            WHERE is_active = 1
            ORDER BY
                display_order ASC,
                id ASC
        """).fetchall()

    return [
        dict(
            row
        )
        for row in rows
    ]


def get_active_user_tags():
    conn = None

    try:
        conn = get_connection()

        conn.row_factory = (
            sqlite3.Row
        )

        tags = _fetch_active_user_tags(
            conn=conn,
            for_settings=False,
        )

        logger.debug(
            (
                "Loaded %d active "
                "user tag(s)"
            ),
            len(
                tags
            ),
        )

        return tags

    except sqlite3.Error:
        logger.exception(
            (
                "Failed to load active "
                "user tags"
            )
        )

        raise

    except Exception:
        logger.exception(
            (
                "Unexpected error while "
                "loading active user tags"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )


def get_user_tags_for_settings():
    conn = None

    try:
        conn = get_connection()

        conn.row_factory = (
            sqlite3.Row
        )

        tags = _fetch_active_user_tags(
            conn=conn,
            for_settings=True,
        )

        logger.debug(
            (
                "Loaded %d user tag(s) "
                "for settings"
            ),
            len(
                tags
            ),
        )

        return tags

    except sqlite3.Error:
        logger.exception(
            (
                "Failed to load user tags "
                "for settings"
            )
        )

        raise

    except Exception:
        logger.exception(
            (
                "Unexpected error while "
                "loading settings tags"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )


def save_user_tags_data(
    tags,
):
    """
    Validate and save the complete active
    user-tag configuration.

    An empty list is valid and deactivates
    all existing user tags.
    """
    validated_tags = (
        _validate_tags_payload(
            tags
        )
    )

    conn = None

    try:
        conn = get_connection()

        conn.row_factory = (
            sqlite3.Row
        )

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        calibration_bounds = (
            _load_calibration_bounds(
                conn
            )
        )

        _validate_roi_bounds(
            tags=validated_tags,
            bounds=calibration_bounds,
        )

        _validate_existing_ids(
            conn=conn,
            tags=validated_tags,
        )

        # ปิด Tag เดิมทั้งหมดก่อน แล้วเปิดเฉพาะ
        # รายการที่ส่งมา ภายใน Transaction เดียวกัน
        conn.execute("""
            UPDATE user_tags
            SET
                is_active = 0,
                updated_at = datetime('now')
            WHERE is_active = 1
        """)

        saved_ids = []

        for tag in validated_tags:
            tag_id = tag[
                "id"
            ]

            if tag_id is None:
                cursor = conn.execute("""
                    INSERT INTO user_tags (
                        tag_name,
                        unit,
                        display_order,
                        sensor_api_key,
                        roi_x1,
                        roi_y1,
                        roi_x2,
                        roi_y2,
                        is_active,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        1,
                        datetime('now'),
                        datetime('now')
                    )
                """, (
                    tag["tag_name"],
                    tag["unit"],
                    tag["display_order"],
                    tag["sensor_api_key"],
                    tag["x1"],
                    tag["y1"],
                    tag["x2"],
                    tag["y2"],
                ))

                tag_id = (
                    cursor.lastrowid
                )

                if tag_id is None:
                    raise RuntimeError(
                        (
                            "Database did not "
                            "return the new tag id"
                        )
                    )

            else:
                conn.execute("""
                    UPDATE user_tags
                    SET
                        tag_name = ?,
                        unit = ?,
                        display_order = ?,
                        sensor_api_key = ?,
                        roi_x1 = ?,
                        roi_y1 = ?,
                        roi_x2 = ?,
                        roi_y2 = ?,
                        is_active = 1,
                        updated_at = datetime('now')
                    WHERE id = ?
                """, (
                    tag["tag_name"],
                    tag["unit"],
                    tag["display_order"],
                    tag["sensor_api_key"],
                    tag["x1"],
                    tag["y1"],
                    tag["x2"],
                    tag["y2"],
                    tag_id,
                ))

            saved_ids.append(
                int(
                    tag_id
                )
            )

        saved_tags = (
            _fetch_active_user_tags(
                conn=conn,
                for_settings=True,
            )
        )

        conn.commit()

        logger.info(
            (
                "Saved %d active "
                "user tag(s)"
            ),
            len(
                saved_tags
            ),
        )

        return {
            "ok": True,
            "message": (
                "User tags saved"
            ),
            "tags": saved_tags,
            "saved_ids": saved_ids,
        }

    except TagValidationError:
        _safe_rollback(
            conn
        )

        raise

    except sqlite3.Error:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Database error while "
                "saving user tags"
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
                "saving user tags"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )