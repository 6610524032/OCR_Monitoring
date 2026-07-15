from app.server.database import get_connection


def reset_configuration_data():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM calibration")
    cur.execute("DELETE FROM user_tags")

    conn.commit()
    conn.close()

    return {
        "ok": True
    }