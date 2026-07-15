from app.server.database import get_connection
from app.server.config import DB_PATH


def init_database():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS calibration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            image_path TEXT,

            p1_x REAL,
            p1_y REAL,
            p2_x REAL,
            p2_y REAL,
            p3_x REAL,
            p3_y REAL,
            p4_x REAL,
            p4_y REAL,

            output_width INTEGER DEFAULT 900,
            output_height INTEGER DEFAULT 700,

            is_active INTEGER DEFAULT 1,

            created_at TEXT,
            updated_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            tag_name TEXT NOT NULL,
            unit TEXT,
            display_order INTEGER DEFAULT 0,

            roi_x1 REAL NOT NULL,
            roi_y1 REAL NOT NULL,
            roi_x2 REAL NOT NULL,
            roi_y2 REAL NOT NULL,

            is_active INTEGER DEFAULT 1,

            created_at TEXT,
            updated_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS camera (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            camera_name TEXT NOT NULL,
            camera_ip TEXT NOT NULL,

            camera_username TEXT NOT NULL,
            camera_password TEXT NOT NULL,

            rtsp_path TEXT NOT NULL,

            is_active INTEGER DEFAULT 1,

            created_at TEXT,
            updated_at TEXT
        )
    """)
    
    cur.execute("""
        INSERT OR IGNORE INTO camera (
            id,
            camera_name,
            camera_ip,
            camera_username,
            camera_password,
            rtsp_path,
            created_at
        )
    
        VALUES (
            1,
            'Camera 1',
            '10.250.3.10',
            'admin',
            'M12345678',
            '/cam/realmonitor?channel=1&subtype=0',
            datetime('now')
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ocr_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            raw_image_path TEXT,
            calibrated_image_path TEXT,

            ocr_time TEXT,

            status TEXT DEFAULT 'NORMAL',
            review_status TEXT DEFAULT 'PENDING',

            missing_tags TEXT,
            alert_message TEXT,

            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ocr_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            run_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,

            tag_name TEXT NOT NULL,
            unit TEXT,

            value TEXT,
            raw_text TEXT,

            created_at TEXT,

            FOREIGN KEY (run_id) REFERENCES ocr_runs(id),
            FOREIGN KEY (tag_id) REFERENCES user_tags(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS summary_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            table_name TEXT NOT NULL,
            tag_signature TEXT NOT NULL,

            is_active INTEGER DEFAULT 1,

            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()


def ensure_database():
    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    init_database()

    print("Database schema is ready.")


if __name__ == "__main__":
    ensure_database()