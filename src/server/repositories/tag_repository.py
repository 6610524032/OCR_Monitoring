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
    if not isinstance(tags, list):
        logger.warning(
            "Invalid tags payload"
        )

        return {
            "ok": False,
            "message": "Tags must be a list",
        }

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    saved_ids = []

    try:
        for index, tag in enumerate(tags):
            tag_name = str(
                tag.get(
                    "tag_name",
                    "",
                )
            ).strip()

            unit = str(
                tag.get(
                    "unit",
                    "",
                )
            ).strip()

            sensor_api_key = str(
                tag.get(
                    "sensor_api_key",
                    "",
                )
            ).strip()

            if not tag_name:
                conn.rollback()

                return {
                    "ok": False,
                    "message": (
                        f"Tag number {index + 1} "
                        "does not have a tag name"
                    ),
                }

            try:
                x1 = float(tag["x1"])
                y1 = float(tag["y1"])
                x2 = float(tag["x2"])
                y2 = float(tag["y2"])

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                conn.rollback()

                return {
                    "ok": False,
                    "message": (
                        f"Tag number {index + 1} "
                        "has invalid ROI coordinates"
                    ),
                }

            raw_id = tag.get("id")
            tag_id = None

            if raw_id not in (
                None,
                "",
            ):
                try:
                    tag_id = int(raw_id)

                except (
                    TypeError,
                    ValueError,
                ):
                    conn.rollback()

                    return {
                        "ok": False,
                        "message": (
                            f"Tag number {index + 1} "
                            "has an invalid id"
                        ),
                    }

            if tag_id is not None:
                cur.execute(
                    """
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
                    """,
                    (
                        tag_name,
                        unit,
                        index + 1,
                        sensor_api_key,
                        x1,
                        y1,
                        x2,
                        y2,
                        tag_id,
                    ),
                )

                if cur.rowcount == 0:
                    conn.rollback()

                    return {
                        "ok": False,
                        "message": (
                            f"Tag id {tag_id} "
                            "was not found"
                        ),
                    }

            else:
                cur.execute(
                    """
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
                    """,
                    (
                        tag_name,
                        unit,
                        index + 1,
                        sensor_api_key,
                        x1,
                        y1,
                        x2,
                        y2,
                    ),
                )

                tag_id = cur.lastrowid

            saved_ids.append(
                tag_id
            )

        if saved_ids:
            placeholders = ", ".join(
                ["?"] * len(saved_ids)
            )

            cur.execute(
                f"""
                UPDATE user_tags
                SET
                    is_active = 0,
                    updated_at = datetime('now')
                WHERE
                    is_active = 1
                    AND id NOT IN (
                        {placeholders}
                    )
                """,
                saved_ids,
            )

        else:
            cur.execute(
                """
                UPDATE user_tags
                SET
                    is_active = 0,
                    updated_at = datetime('now')
                WHERE is_active = 1
                """
            )

        cur.execute(
            """
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
            """
        )

        saved_tags = [
            dict(row)
            for row in cur.fetchall()
        ]

        conn.commit()

        logger.info(
            "Saved %d active user tag(s)",
            len(saved_tags),
        )

        return {
            "ok": True,
            "message": "User tags saved",
            "tags": saved_tags,
        }

    except Exception:
        conn.rollback()

        logger.exception(
            "Failed to save user tags"
        )

        raise

    finally:
        conn.close()