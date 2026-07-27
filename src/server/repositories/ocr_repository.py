from datetime import datetime

from src.logger import create_logger
from src.server.database import (
    get_connection,
    to_relative_path
)
from src.server.repositories.summary_repository import (
    save_summary_row
)


logger = create_logger(
    "server.repositories.ocr"
)


def create_ocr_run(
    raw_image_path,
    calibrated_image_path,
    status,
    missing_tags,
    alert_message
):
    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    review_status = (
        "ACCEPTED"
        if status == "NORMAL"
        else "PENDING"
    )

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO ocr_runs (
                raw_image_path,
                calibrated_image_path,
                ocr_time,
                status,
                review_status,
                missing_tags,
                alert_message,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            to_relative_path(raw_image_path),
            to_relative_path(calibrated_image_path),
            now,
            status,
            review_status,
            ",".join(missing_tags),
            alert_message,
            now
        ))

        run_id = cur.lastrowid

        conn.commit()

        logger.info(
            "OCR run %s created",
            run_id
        )

        return run_id

    except Exception:
        conn.rollback()

        logger.exception(
            "Failed to create OCR run"
        )

        raise

    finally:
        conn.close()


def save_ocr_value(
    run_id,
    tag,
    value,
    raw_text
):
    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
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
        """, (
            run_id,
            tag["id"],
            tag["tag_name"],
            tag.get("unit", ""),
            value,
            raw_text,
            now
        ))

        conn.commit()

        logger.info(
            "Saved OCR value for run %s",
            run_id
        )

    except Exception:
        conn.rollback()

        logger.exception(
            "Failed to save OCR value"
        )

        raise

    finally:
        conn.close()


def save_worker_ocr_run(
    raw_image_path,
    calibrated_image_path,
    results,
    status,
    missing_tags,
    alert_message,
    captured_at
):
    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    review_status = (
        "ACCEPTED"
        if status == "NORMAL"
        else "PENDING"
    )

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO ocr_runs (
                raw_image_path,
                calibrated_image_path,
                ocr_time,
                status,
                review_status,
                missing_tags,
                alert_message,
                captured_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            to_relative_path(raw_image_path),
            to_relative_path(calibrated_image_path),
            now,
            status,
            review_status,
            ",".join(missing_tags),
            alert_message,
            captured_at,
            now
        ))

        run_id = cur.lastrowid

        for item in results:
            tag = item["tag"]

            cur.execute("""
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
            """, (
                run_id,
                tag["id"],
                tag["tag_name"],
                tag.get("unit", ""),
                str(item.get("value", "")),
                str(item.get("raw_text", "")),
                now
            ))

        conn.commit()

        logger.info(
            "Worker OCR run %s saved with %d value(s)",
            run_id,
            len(results)
        )

    except Exception:
        conn.rollback()

        logger.exception(
            "Failed to save worker OCR run"
        )

        raise

    finally:
        conn.close()

    save_summary_row(
        run_id=run_id,
        edit_type="OCR"
    )

    logger.info(
        "Summary row created for run %s",
        run_id
    )

    return run_id