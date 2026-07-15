import sqlite3

from app.server.database import (
    get_connection,
    to_relative_path
)


def get_active_user_tags():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            tag_name,
            unit,
            roi_x1,
            roi_y1,
            roi_x2,
            roi_y2,
            display_order
        FROM user_tags
        WHERE is_active = 1
        ORDER BY display_order ASC, id ASC
    """)

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]

def get_user_tags_for_settings():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            tag_name,
            tag_name AS display_name,
            unit,
            roi_x1 AS x1,
            roi_y1 AS y1,
            roi_x2 AS x2,
            roi_y2 AS y2,
            is_active
        FROM user_tags
        WHERE is_active = 1
        ORDER BY id
    """)

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def save_user_tags_data(tags):
    if not tags:
        return {
            "ok": False,
            "message": "No tags received"
        }

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("UPDATE user_tags SET is_active = 0")

    for index, tag in enumerate(tags):
        cur.execute("""
            INSERT INTO user_tags (
                tag_name,
                unit,
                display_order,
                roi_x1,
                roi_y1,
                roi_x2,
                roi_y2,
                is_active,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
        """, (
            tag["tag_name"],
            tag.get("unit", ""),
            index + 1,
            tag["x1"],
            tag["y1"],
            tag["x2"],
            tag["y2"]
        ))

    conn.commit()
    conn.close()

    return {
        "ok": True,
        "message": "User tags saved"
    }