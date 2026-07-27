import sqlite3

from src.logger import create_logger
from src.server.database import get_connection


logger = create_logger(
    "server.repositories.tag"
)


def get_active_user_tags():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("""
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
        """)

        rows = cur.fetchall()

        tags = [
            dict(row)
            for row in rows
        ]

        logger.info(
            "Loaded %d active tag(s)",
            len(tags)
        )

        return tags

    except Exception:
        logger.exception(
            "Failed to load active user tags"
        )
        raise

    finally:
        conn.close()


def get_user_tags_for_settings():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("""
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
                is_active
            FROM user_tags
            WHERE is_active = 1
            ORDER BY
                display_order ASC,
                id ASC
        """)

        rows = cur.fetchall()

        tags = [
            dict(row)
            for row in rows
        ]

        logger.info(
            "Loaded %d tag(s) for settings",
            len(tags)
        )

        return tags

    except Exception:
        logger.exception(
            "Failed to load settings tags"
        )
        raise

    finally:
        conn.close()


def save_user_tags_data(tags):
    if not tags:
        logger.warning(
            "No tags received to save"
        )

        return {
            "ok": False,
            "message": "No tags received"
        }

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            UPDATE user_tags
            SET
                is_active = 0,
                updated_at = datetime('now')
        """)

        for index, tag in enumerate(tags):
            tag_name = str(
                tag.get(
                    "tag_name",
                    ""
                )
            ).strip()

            sensor_api_key = str(
                tag.get(
                    "sensor_api_key",
                    ""
                )
            ).strip()

            if not tag_name:
                conn.rollback()

                logger.warning(
                    "Tag %d has no tag name",
                    index + 1
                )

                return {
                    "ok": False,
                    "message": (
                        f"Tag number {index + 1} "
                        "does not have a tag name"
                    )
                }

            cur.execute("""
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
                tag_name,
                str(
                    tag.get(
                        "unit",
                        ""
                    )
                ).strip(),
                index + 1,
                sensor_api_key,
                tag["x1"],
                tag["y1"],
                tag["x2"],
                tag["y2"]
            ))

        conn.commit()

        logger.info(
            "Saved %d user tag(s)",
            len(tags)
        )

    except Exception:
        conn.rollback()

        logger.exception(
            "Failed to save user tags"
        )

        raise

    finally:
        conn.close()

    return {
        "ok": True,
        "message": "User tags saved"
    }