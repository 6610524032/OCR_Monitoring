import sqlite3
from pathlib import Path

from src.server.config import (
    CALIBRATED_IMAGES_DIR,
    DB_DIR,
    DB_PATH,
    RAW_IMAGES_DIR,
)


SUMMARY_SCHEMA_VERSION = 2


def get_connection():
    DB_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    return sqlite3.connect(
        DB_PATH
    )


def table_exists(
    cursor,
    table_name,
):
    cursor.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    )

    return (
        cursor.fetchone()
        is not None
    )


def normalize_image_path(
    image_path,
    base_dir,
):
    if not image_path:
        return None

    path = Path(
        str(image_path)
    )

    try:
        if path.is_absolute():
            return str(
                path.relative_to(
                    base_dir
                )
            ).replace(
                "\\",
                "/",
            )

    except ValueError:
        pass

    text = str(
        image_path
    ).replace(
        "\\",
        "/",
    )

    marker = (
        str(base_dir).replace(
            "\\",
            "/",
        )
        + "/"
    )

    if marker in text:
        return text.split(
            marker,
            1,
        )[1]

    return text


def to_relative_path(path):
    if path is None:
        return ""

    text = str(path).replace(
        "\\",
        "/",
    )

    if "raw_images" in text:
        return normalize_image_path(
            image_path=path,
            base_dir=RAW_IMAGES_DIR,
        )

    if "calibrated_images" in text:
        return normalize_image_path(
            image_path=path,
            base_dir=CALIBRATED_IMAGES_DIR,
        )

    return text


def parse_numeric_value(value):
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    try:
        return float(text)

    except (
        TypeError,
        ValueError,
    ):
        return None


def is_normal_run(
    status,
    missing_tags,
):
    return (
        status == "NORMAL"
        and not missing_tags
    )


def build_tag_signature(tags):
    parts = [
        (
            f"{tag['tag_name']}|"
            f"{tag.get('unit', '')}|"
            f"{tag.get('display_order', '')}"
        )
        for tag in tags
    ]

    tag_signature = "||".join(
        parts
    )

    return (
        f"schema-{SUMMARY_SCHEMA_VERSION}"
        f"||{tag_signature}"
    )


def make_summary_column_name(
    tag_name,
    unit,
):
    clean_tag_name = str(
        tag_name
    ).strip()

    clean_unit = str(
        unit or ""
    ).strip()

    if clean_unit:
        return (
            f"{clean_tag_name} "
            f"({clean_unit})"
        )

    return clean_tag_name


def get_or_create_active_summary_table(
    tags,
):
    if not tags:
        raise ValueError(
            "Cannot create summary table "
            "without active tags"
        )

    tag_signature = (
        build_tag_signature(
            tags
        )
    )

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT
                table_name,
                tag_signature
            FROM summary_versions
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
            """
        )

        active = cursor.fetchone()

        if (
            active
            and active["tag_signature"]
            == tag_signature
        ):
            return active[
                "table_name"
            ]

        cursor.execute(
            """
            UPDATE summary_versions
            SET is_active = 0
            WHERE is_active = 1
            """
        )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM summary_versions
            """
        )

        version_count = (
            cursor.fetchone()[0]
        )

        version_number = (
            version_count + 1
        )

        table_name = (
            f"ocr_summary_v"
            f"{version_number}"
        )

        tag_columns = []

        for tag in tags:
            column_name = (
                make_summary_column_name(
                    tag["tag_name"],
                    tag.get(
                        "unit",
                        "",
                    ),
                )
            )

            tag_columns.append(
                f'"{column_name}" TEXT'
            )

        tag_columns_sql = ",\n"
        tag_columns_sql = (
            tag_columns_sql.join(
                tag_columns
            )
        )

        create_sql = f"""
            CREATE TABLE "{table_name}" (
                run_id INTEGER PRIMARY KEY,
                ocr_status TEXT,
                ocr_time TEXT,
                {tag_columns_sql},
                created_at TEXT
            )
        """

        cursor.execute(
            create_sql
        )

        cursor.execute(
            """
            INSERT INTO summary_versions (
                table_name,
                tag_signature,
                is_active,
                created_at
            )
            VALUES (
                ?,
                ?,
                1,
                datetime('now')
            )
            """,
            (
                table_name,
                tag_signature,
            ),
        )

        conn.commit()

        return table_name

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()