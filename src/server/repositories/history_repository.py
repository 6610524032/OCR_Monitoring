import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from src.logger import create_logger
from src.server.config import (
    CALIBRATED_IMAGES_DIR,
    DB_PATH,
    RAW_IMAGES_DIR,
)
from src.server.database import (
    get_connection,
    is_normal_run,
    normalize_image_path,
    parse_numeric_value,
    table_exists,
)


logger = create_logger(
    "server.repositories.history"
)


MAX_ALERT_RUNS = 500
MAX_HISTORY_POINTS = 10_000
MAX_HISTORY_VARIABLES = 1_000
MAX_VALUES_PER_RUN = 5_000
MAX_PATH_LENGTH = 2_048


def _safe_close(
    conn,
):
    if conn is None:
        return

    try:
        conn.close()

    except sqlite3.Error:
        logger.exception(
            (
                "Failed to close History "
                "database connection"
            )
        )


def _database_exists():
    try:
        database_path = Path(
            DB_PATH
        )

        return (
            database_path.exists()
            and database_path.is_file()
        )

    except OSError:
        logger.exception(
            (
                "Cannot inspect History "
                "database path"
            )
        )

        return False


def _tables_exist(
    conn,
    *table_names,
):
    cursor = conn.cursor()

    return all(
        table_exists(
            cursor,
            table_name,
        )
        for table_name in table_names
    )


def _clean_text(
    value,
    max_length=2_000,
):
    if value is None:
        return ""

    try:
        text = str(
            value
        ).strip()

    except Exception:
        return ""

    return text.replace(
        "\x00",
        "",
    )[:max_length]


def _safe_image_path(
    image_path,
    base_dir,
):
    if not image_path:
        return ""

    try:
        normalized = (
            normalize_image_path(
                image_path,
                base_dir,
            )
        )

    except Exception:
        logger.exception(
            (
                "Cannot normalize stored "
                "History image path"
            )
        )

        return ""

    if not normalized:
        return ""

    path_text = (
        str(
            normalized
        )
        .strip()
        .replace(
            "\\",
            "/",
        )
    )

    if (
        not path_text
        or "\x00" in path_text
        or len(
            path_text
        )
        > MAX_PATH_LENGTH
    ):
        logger.warning(
            (
                "Stored History image "
                "path was rejected"
            )
        )

        return ""

    relative_path = PurePosixPath(
        path_text
    )

    if (
        relative_path.is_absolute()
        or ".." in relative_path.parts
        or (
            relative_path.parts
            and ":" in relative_path.parts[0]
        )
    ):
        logger.warning(
            (
                "Unsafe stored History "
                "image path was ignored"
            )
        )

        return ""

    return relative_path.as_posix()


def _image_url(
    route_prefix,
    relative_path,
):
    if not relative_path:
        return None

    return (
        route_prefix.rstrip(
            "/"
        )
        + "/"
        + relative_path.lstrip(
            "/"
        )
    )


def _preferred_time(
    run,
):
    return _clean_text(
        (
            run.get(
                "captured_at"
            )
            or run.get(
                "ocr_time"
            )
            or run.get(
                "created_at"
            )
            or ""
        ),
        100,
    )


def _format_time_label(
    value,
):
    text = _clean_text(
        value,
        100,
    )

    if not text:
        return ""

    normalized = (
        text[:-1]
        + "+00:00"
        if text.endswith(
            "Z"
        )
        else text
    )

    try:
        parsed = (
            datetime.fromisoformat(
                normalized
            )
        )

        return parsed.strftime(
            "%d/%m %H:%M"
        )

    except ValueError:
        return text


def _is_normal(
    status,
    missing_tags,
):
    return is_normal_run(
        _clean_text(
            status,
            50,
        ).upper(),
        _clean_text(
            missing_tags
        ),
    )


def _value_payload(
    row,
):
    item = dict(
        row
    )

    return {
        "id": item.get(
            "id"
        ),
        "tag_id": item.get(
            "tag_id"
        ),
        "tag_name": _clean_text(
            item.get(
                "tag_name"
            ),
            150,
        ),
        "unit": _clean_text(
            item.get(
                "unit"
            ),
            100,
        ),
        "value": _clean_text(
            item.get(
                "value"
            ),
            500,
        ),
        "raw_text": _clean_text(
            item.get(
                "raw_text"
            ),
            2_000,
        ),
        "created_at": _clean_text(
            item.get(
                "created_at"
            ),
            100,
        ),
    }


def get_latest_log():
    conn = None

    try:
        if not _database_exists():
            return None

        conn = get_connection()

        conn.row_factory = (
            sqlite3.Row
        )

        if not _tables_exist(
            conn,
            "ocr_runs",
            "ocr_values",
        ):
            return None

        run_row = conn.execute("""
            SELECT *
            FROM ocr_runs
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        if run_row is None:
            return None

        run = dict(
            run_row
        )

        run_id = int(
            run["id"]
        )

        value_rows = conn.execute("""
            SELECT
                id,
                tag_id,
                tag_name,
                unit,
                value,
                raw_text,
                created_at
            FROM ocr_values
            WHERE run_id = ?
            ORDER BY id ASC
            LIMIT ?
        """, (
            run_id,
            MAX_VALUES_PER_RUN,
        )).fetchall()

        values = [
            _value_payload(
                row
            )
            for row in value_rows
        ]

        raw_path = _safe_image_path(
            run.get(
                "raw_image_path"
            ),
            RAW_IMAGES_DIR,
        )

        calibrated_path = (
            _safe_image_path(
                run.get(
                    "calibrated_image_path"
                ),
                CALIBRATED_IMAGES_DIR,
            )
        )

        logger.debug(
            (
                "Latest OCR History loaded: "
                "run_id=%s"
            ),
            run_id,
        )

        return {
            "id": run_id,
            "run_id": run_id,
            "ocr_time": (
                _preferred_time(
                    run
                )
                or "-"
            ),
            "captured_at": _clean_text(
                run.get(
                    "captured_at"
                ),
                100,
            ),
            "status": (
                _clean_text(
                    run.get(
                        "status"
                    ),
                    50,
                )
                or "UNKNOWN"
            ),
            "missing_tags": _clean_text(
                run.get(
                    "missing_tags"
                )
            ),
            "alert_message": _clean_text(
                run.get(
                    "alert_message"
                )
            ),
            "raw_image_path": (
                raw_path
            ),
            "calibrated_image_path": (
                calibrated_path
            ),
            "raw_image_url": _image_url(
                "/raw_images",
                raw_path,
            ),
            "calibrated_image_url": (
                _image_url(
                    "/calibrated_images",
                    calibrated_path,
                )
            ),
            "values": values,
            "value_count": len(
                values
            ),
            "is_normal": _is_normal(
                run.get(
                    "status"
                ),
                run.get(
                    "missing_tags"
                ),
            ),
        }

    except Exception:
        logger.exception(
            (
                "Failed to load latest "
                "OCR History"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )


def get_abnormal_history_runs():
    conn = None

    try:
        if not _database_exists():
            return []

        conn = get_connection()

        conn.row_factory = (
            sqlite3.Row
        )

        if not _tables_exist(
            conn,
            "ocr_runs",
        ):
            return []

        rows = conn.execute("""
            SELECT
                id,
                captured_at,
                ocr_time,
                status,
                missing_tags,
                alert_message,
                created_at
            FROM ocr_runs
            WHERE
                COALESCE(
                    UPPER(
                        TRIM(status)
                    ),
                    ''
                ) <> 'NORMAL'
                OR COALESCE(
                    TRIM(missing_tags),
                    ''
                ) <> ''
            ORDER BY id DESC
            LIMIT ?
        """, (
            MAX_ALERT_RUNS,
        )).fetchall()

        items = []

        for row in rows:
            item = dict(
                row
            )

            item[
                "ocr_time"
            ] = _preferred_time(
                item
            )

            item[
                "status"
            ] = (
                _clean_text(
                    item.get(
                        "status"
                    ),
                    50,
                )
                or "UNKNOWN"
            )

            item[
                "missing_tags"
            ] = _clean_text(
                item.get(
                    "missing_tags"
                )
            )

            item[
                "alert_message"
            ] = _clean_text(
                item.get(
                    "alert_message"
                )
            )

            item[
                "is_normal"
            ] = False

            items.append(
                item
            )

        logger.debug(
            (
                "Loaded %d abnormal "
                "OCR History run(s)"
            ),
            len(
                items
            ),
        )

        return items

    except Exception:
        logger.exception(
            (
                "Failed to load abnormal "
                "OCR History"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )


def get_history_run_detail(
    run_id,
):
    try:
        run_id = int(
            run_id
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise ValueError(
            "run_id must be an integer"
        ) from error

    if run_id <= 0:
        raise ValueError(
            (
                "run_id must be greater "
                "than zero"
            )
        )

    conn = None

    try:
        if not _database_exists():
            return None

        conn = get_connection()

        conn.row_factory = (
            sqlite3.Row
        )

        if not _tables_exist(
            conn,
            "ocr_runs",
            "ocr_values",
        ):
            return None

        run_row = conn.execute("""
            SELECT *
            FROM ocr_runs
            WHERE id = ?
            LIMIT 1
        """, (
            run_id,
        )).fetchone()

        if run_row is None:
            return None

        run = dict(
            run_row
        )

        value_rows = conn.execute("""
            SELECT
                id,
                tag_id,
                tag_name,
                unit,
                value,
                raw_text,
                created_at
            FROM ocr_values
            WHERE run_id = ?
            ORDER BY id ASC
            LIMIT ?
        """, (
            run_id,
            MAX_VALUES_PER_RUN,
        )).fetchall()

        values = [
            _value_payload(
                row
            )
            for row in value_rows
        ]

        raw_path = _safe_image_path(
            run.get(
                "raw_image_path"
            ),
            RAW_IMAGES_DIR,
        )

        calibrated_path = (
            _safe_image_path(
                run.get(
                    "calibrated_image_path"
                ),
                CALIBRATED_IMAGES_DIR,
            )
        )

        run_payload = {
            "id": run_id,
            "run_id": run_id,
            "ocr_time": _preferred_time(
                run
            ),
            "captured_at": _clean_text(
                run.get(
                    "captured_at"
                ),
                100,
            ),
            "status": (
                _clean_text(
                    run.get(
                        "status"
                    ),
                    50,
                )
                or "UNKNOWN"
            ),
            "missing_tags": _clean_text(
                run.get(
                    "missing_tags"
                )
            ),
            "alert_message": _clean_text(
                run.get(
                    "alert_message"
                )
            ),
            "raw_image_path": raw_path,
            "calibrated_image_path": (
                calibrated_path
            ),
            "raw_image_url": _image_url(
                "/raw_images",
                raw_path,
            ),
            "calibrated_image_url": (
                _image_url(
                    "/calibrated_images",
                    calibrated_path,
                )
            ),
            "is_normal": _is_normal(
                run.get(
                    "status"
                ),
                run.get(
                    "missing_tags"
                ),
            ),
        }

        logger.debug(
            (
                "History run detail loaded: "
                "run_id=%s"
            ),
            run_id,
        )

        return {
            "run": run_payload,
            "values": values,
        }

    except Exception:
        logger.exception(
            (
                "Failed to load History "
                "run detail: run_id=%s"
            ),
            run_id,
        )

        raise

    finally:
        _safe_close(
            conn
        )


def get_history_data(
    tag_name,
    days=2,
):
    if not isinstance(
        tag_name,
        str,
    ):
        raise ValueError(
            "tag_name must be a string"
        )

    tag_name = tag_name.strip()

    if not tag_name:
        raise ValueError(
            "tag_name is required"
        )

    if (
        "\x00" in tag_name
        or len(
            tag_name
        ) > 150
    ):
        raise ValueError(
            "tag_name is invalid"
        )

    try:
        days = int(
            days
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise ValueError(
            "days must be an integer"
        ) from error

    if (
        days <= 0
        or days > 365
    ):
        raise ValueError(
            (
                "days must be between "
                "1 and 365"
            )
        )

    start_time = (
        datetime.now()
        - timedelta(
            days=days
        )
    ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = None

    try:
        if not _database_exists():
            return []

        conn = get_connection()

        conn.row_factory = (
            sqlite3.Row
        )

        if not _tables_exist(
            conn,
            "ocr_runs",
            "ocr_values",
        ):
            return []

        rows = conn.execute("""
            SELECT *
            FROM (
                SELECT
                    r.id AS run_id,
                    r.captured_at,
                    r.ocr_time,
                    r.created_at,
                    r.status,
                    r.missing_tags,
                    v.unit,
                    v.value,
                    COALESCE(
                        NULLIF(
                            r.ocr_time,
                            ''
                        ),
                        r.created_at
                    ) AS sort_time
                FROM ocr_runs AS r
                INNER JOIN ocr_values AS v
                    ON v.id = (
                        SELECT MAX(v2.id)
                        FROM ocr_values AS v2
                        WHERE
                            v2.run_id = r.id
                            AND v2.tag_name = ?
                    )
                WHERE
                    datetime(
                        COALESCE(
                            NULLIF(
                                r.ocr_time,
                                ''
                            ),
                            r.created_at
                        )
                    ) >= datetime(?)
                ORDER BY
                    datetime(
                        COALESCE(
                            NULLIF(
                                r.ocr_time,
                                ''
                            ),
                            r.created_at
                        )
                    ) DESC,
                    r.id DESC
                LIMIT ?
            ) AS recent_points
            ORDER BY
                datetime(sort_time) ASC,
                run_id ASC
        """, (
            tag_name,
            start_time,
            MAX_HISTORY_POINTS,
        )).fetchall()

        points = []

        for row in rows:
            numeric_value = (
                parse_numeric_value(
                    row["value"]
                )
            )

            if numeric_value is None:
                continue

            try:
                numeric_value = float(
                    numeric_value
                )

            except (
                TypeError,
                ValueError,
                OverflowError,
            ):
                continue

            if not math.isfinite(
                numeric_value
            ):
                continue

            row_data = dict(
                row
            )

            display_time = (
                _preferred_time(
                    row_data
                )
            )

            points.append({
                "run_id": int(
                    row["run_id"]
                ),
                "ocr_time": display_time,
                "captured_at": _clean_text(
                    row[
                        "captured_at"
                    ],
                    100,
                ),
                "time_label": (
                    _format_time_label(
                        display_time
                    )
                ),
                "value": numeric_value,
                "unit": _clean_text(
                    row["unit"],
                    100,
                ),
                "status": (
                    _clean_text(
                        row["status"],
                        50,
                    )
                    or "UNKNOWN"
                ),
                "missing_tags": _clean_text(
                    row[
                        "missing_tags"
                    ]
                ),
                "is_normal": _is_normal(
                    row["status"],
                    row[
                        "missing_tags"
                    ],
                ),
            })

        logger.debug(
            (
                "History chart data loaded: "
                "tag=%s, days=%d, points=%d"
            ),
            tag_name,
            days,
            len(
                points
            ),
        )

        return points

    except Exception:
        logger.exception(
            (
                "Failed to load History "
                "data for tag: %s"
            ),
            tag_name,
        )

        raise

    finally:
        _safe_close(
            conn
        )


def get_history_variables():
    conn = None

    try:
        if not _database_exists():
            return []

        conn = get_connection()

        conn.row_factory = (
            sqlite3.Row
        )

        has_tags = _tables_exist(
            conn,
            "user_tags",
        )

        has_values = _tables_exist(
            conn,
            "ocr_values",
        )

        if not (
            has_tags
            or has_values
        ):
            return []

        active_rows = []

        if has_tags:
            active_rows = conn.execute("""
                SELECT
                    tag_name,
                    unit
                FROM user_tags
                WHERE is_active = 1
                ORDER BY
                    display_order ASC,
                    id ASC
                LIMIT ?
            """, (
                MAX_HISTORY_VARIABLES,
            )).fetchall()

        historical_rows = []

        if has_values:
            historical_rows = conn.execute("""
                SELECT
                    current_value.tag_name,
                    current_value.unit
                FROM ocr_values AS current_value
                INNER JOIN (
                    SELECT
                        tag_name,
                        MAX(id) AS latest_id
                    FROM ocr_values
                    WHERE
                        COALESCE(
                            TRIM(tag_name),
                            ''
                        ) <> ''
                    GROUP BY tag_name
                ) AS latest_value
                    ON latest_value.latest_id
                    = current_value.id
                ORDER BY
                    latest_value.latest_id ASC
                LIMIT ?
            """, (
                MAX_HISTORY_VARIABLES,
            )).fetchall()

        variables = []
        seen_names = set()

        for row in (
            list(
                active_rows
            )
            + list(
                historical_rows
            )
        ):
            tag_name = _clean_text(
                row["tag_name"],
                150,
            )

            if not tag_name:
                continue

            name_key = (
                tag_name.casefold()
            )

            if name_key in {
                "date",
                "time",
            }:
                continue

            if name_key in seen_names:
                continue

            seen_names.add(
                name_key
            )

            variables.append({
                "tag_name": tag_name,
                "unit": _clean_text(
                    row["unit"],
                    100,
                ),
            })

            if (
                len(
                    variables
                )
                >= MAX_HISTORY_VARIABLES
            ):
                break

        logger.debug(
            (
                "Loaded %d History "
                "variable(s)"
            ),
            len(
                variables
            ),
        )

        return variables

    except Exception:
        logger.exception(
            (
                "Failed to load "
                "History variables"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )