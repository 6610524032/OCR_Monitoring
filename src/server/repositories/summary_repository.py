from datetime import datetime

import sqlite3

from src.server.database import (
    get_connection,
    get_or_create_active_summary_table,
    make_summary_column_name
)


def save_summary_row(run_id, edit_type="OCR"):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM ocr_runs
        WHERE id = ?
        LIMIT 1
    """, (run_id,))

    run = cur.fetchone()

    if run is None:
        conn.close()
        return

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

    values = [dict(row) for row in cur.fetchall()]

    cur.execute("""
        SELECT
            tag_name,
            unit,
            display_order
        FROM user_tags
        WHERE is_active = 1
        ORDER BY display_order ASC, id ASC
    """)

    tags = [dict(row) for row in cur.fetchall()]

    conn.close()

    if not tags:
        return

    table_name = get_or_create_active_summary_table(tags)

    value_map = {}

    for item in values:
        column_name = make_summary_column_name(
            item["tag_name"],
            item.get("unit", "")
        )

        value_map[column_name] = item.get("value", "")

    columns = [
        "run_id",
        "ocr_status",
        "review_status",
        "edit_type",
        "ocr_time"
    ]

    row_values = [
        run["id"],
        run["status"] or "",
        run["review_status"] or "",
        edit_type,
        run["ocr_time"] or run["created_at"] or ""
    ]

    for tag in tags:
        column_name = make_summary_column_name(
            tag["tag_name"],
            tag.get("unit", "")
        )

        columns.append(column_name)
        row_values.append(value_map.get(column_name, ""))

    columns.append("created_at")
    row_values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    placeholders = ", ".join(["?"] * len(columns))
    quoted_columns = ", ".join([f'"{col}"' for col in columns])

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        f"""
        DELETE FROM {table_name}
        WHERE run_id = ?
        """,
        (run_id,)
    )

    cur.execute(
        f"""
        INSERT INTO {table_name} (
            {quoted_columns}
        )
        VALUES (
            {placeholders}
        )
        """,
        row_values
    )

    conn.commit()
    conn.close()