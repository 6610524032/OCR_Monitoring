from datetime import datetime, timedelta

import sqlite3

from src.logger import create_logger
from src.server.config import (
    CALIBRATED_IMAGES_DIR,
    DB_PATH,
    RAW_IMAGES_DIR
)
from src.server.database import (
    get_connection,
    is_normal_run,
    normalize_image_path,
    parse_numeric_value,
    table_exists
)


logger = create_logger(
    "server.repositories.history"
)


def get_latest_log():
    conn = None

    try:
        if not DB_PATH.exists():
            logger.info(
                "No OCR history found"
            )
            return None

        conn = get_connection()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        if (
            not table_exists(cur, "ocr_runs")
            or not table_exists(cur, "ocr_values")
        ):
            logger.info(
                "OCR history tables do not exist"
            )
            return None

        cur.execute("""
            SELECT *
            FROM ocr_runs
            ORDER BY id DESC
            LIMIT 1
        """)

        run = cur.fetchone()

        if run is None:
            logger.info(
                "No OCR history found"
            )
            return None

        run_dict = dict(run)
        run_id = run_dict["id"]

        cur.execute("""
            SELECT
                tag_name,
                unit,
                value,
                raw_text,
                created_at
            FROM ocr_values
            WHERE run_id = ?
            ORDER BY id
        """, (run_id,))

        value_rows = [
            dict(row)
            for row in cur.fetchall()
        ]

        calibrated_image_path = normalize_image_path(
            run_dict.get(
                "calibrated_image_path"
            ),
            CALIBRATED_IMAGES_DIR
        )

        raw_image_path = normalize_image_path(
            run_dict.get(
                "raw_image_path"
            ),
            RAW_IMAGES_DIR
        )

        logger.info(
            "Latest OCR log loaded"
        )

        return {
            "id": run_id,
            "ocr_time": (
                run_dict.get("ocr_time")
                or run_dict.get("created_at")
                or "-"
            ),
            "status": (
                run_dict.get("status")
                or "UNKNOWN"
            ),
            "ocr_status": (
                run_dict.get("status")
                or "UNKNOWN"
            ),
            "missing_tags": (
                run_dict.get("missing_tags")
                or ""
            ),
            "alert_message": (
                run_dict.get("alert_message")
                or ""
            ),
            "raw_image_path": (
                raw_image_path
            ),
            "calibrated_image_path": (
                calibrated_image_path
            ),
            "values": value_rows,
            "value_count": len(
                value_rows
            ),
        }

    except Exception:
        logger.exception(
            "Failed to load latest OCR log"
        )
        raise

    finally:
        if conn is not None:
            conn.close()


def get_history_runs(limit=50):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT
                id,
                ocr_time,
                status,
                review_status,
                missing_tags,
                alert_message,
                raw_image_path,
                calibrated_image_path,
                created_at
            FROM ocr_runs
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))

        runs = [
            dict(row)
            for row in cur.fetchall()
        ]

        logger.info(
            "Loaded %d history run(s)",
            len(runs)
        )

        return runs

    except Exception:
        logger.exception(
            "Failed to load history runs"
        )
        raise

    finally:
        conn.close()


def get_history_run_detail(run_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT *
            FROM ocr_runs
            WHERE id = ?
            LIMIT 1
        """, (run_id,))

        run = cur.fetchone()

        if run is None:
            logger.info(
                "History run %s not found",
                run_id
            )
            return None

        run_dict = dict(run)

        cur.execute("""
            SELECT
                tag_name,
                unit,
                value,
                raw_text
            FROM ocr_values
            WHERE run_id = ?
            ORDER BY id
        """, (run_id,))

        values = [
            dict(row)
            for row in cur.fetchall()
        ]

        raw_path = (
            run_dict.get(
                "raw_image_path"
            )
            or ""
        )

        calibrated_path = (
            run_dict.get(
                "calibrated_image_path"
            )
            or ""
        )

        normal = is_normal_run(
            run_dict.get("status"),
            run_dict.get("missing_tags")
        )

        run_payload = {
            "id": run_dict.get("id"),
            "ocr_time": (
                run_dict.get("ocr_time")
                or run_dict.get(
                    "created_at"
                )
                or ""
            ),
            "status": (
                run_dict.get("status")
                or ""
            ),
            "missing_tags": (
                run_dict.get(
                    "missing_tags"
                )
                or ""
            ),
            "alert_message": (
                run_dict.get(
                    "alert_message"
                )
                or ""
            ),
            "raw_image_path": (
                raw_path
            ),
            "calibrated_image_path": (
                calibrated_path
            ),
            "raw_image_url": (
                "/raw_images/" + raw_path
                if raw_path
                else None
            ),
            "calibrated_image_url": (
                "/calibrated_images/"
                + calibrated_path
                if calibrated_path
                else None
            ),
            "is_normal": normal
        }

        logger.info(
            "Loaded history detail for run %s",
            run_id
        )

        return {
            "run": run_payload,
            "values": values
        }

    except Exception:
        logger.exception(
            "Failed to load history detail"
        )
        raise

    finally:
        conn.close()


def get_history_data(tag_name, days=2):
    start_time = (
        datetime.now() - timedelta(days=days)
    ).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT
                r.id AS run_id,
                r.ocr_time,
                r.status,
                r.missing_tags,
                r.alert_message,
                r.raw_image_path,
                r.calibrated_image_path,
                v.tag_name,
                v.unit,
                v.value,
                v.raw_text
            FROM ocr_runs r
            LEFT JOIN ocr_values v
                ON v.run_id = r.id
                AND v.tag_name = ?
            WHERE r.ocr_time >= ?
            ORDER BY r.ocr_time ASC
        """, (
            tag_name,
            start_time
        ))

        rows = cur.fetchall()

        points = []

        for row in rows:
            numeric_value = parse_numeric_value(
                row["value"]
            )

            if numeric_value is None:
                continue

            ocr_time = row["ocr_time"] or ""

            try:
                dt = datetime.strptime(
                    ocr_time,
                    "%Y-%m-%d %H:%M:%S"
                )

                time_label = dt.strftime(
                    "%d/%m %H:%M"
                )

            except (TypeError, ValueError):
                time_label = ocr_time

            normal = is_normal_run(
                row["status"],
                row["missing_tags"]
            )

            points.append({
                "run_id": row["run_id"],
                "ocr_time": ocr_time,
                "time_label": time_label,
                "value": numeric_value,
                "unit": row["unit"] or "",
                "status": row["status"] or "",
                "missing_tags": (
                    row["missing_tags"] or ""
                ),
                "is_normal": normal
            })

        logger.info(
            "Loaded %d history point(s) for tag '%s'",
            len(points),
            tag_name
        )

        return points

    except Exception:
        logger.exception(
            "Failed to load history data"
        )
        raise

    finally:
        conn.close()


def get_history_variables():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT
                tag_name,
                unit
            FROM user_tags
            WHERE is_active = 1
            ORDER BY id
        """)

        rows = cur.fetchall()

        variables = []

        for row in rows:
            tag_name = row["tag_name"]

            if tag_name.upper() in [
                "DATE",
                "TIME"
            ]:
                continue

            variables.append({
                "tag_name": tag_name,
                "unit": row["unit"] or ""
            })

        logger.info(
            "Loaded %d history variable(s)",
            len(variables)
        )

        return variables

    except Exception:
        logger.exception(
            "Failed to load history variables"
        )
        raise

    finally:
        conn.close()