from app.server.database import get_connection


def reset_configuration_data():
    conn = get_connection()
    cur = conn.cursor()

    # Reset calibration
    cur.execute("DELETE FROM calibration")

    # Reset user tags
    cur.execute("DELETE FROM user_tags")

    # Reset camera configuration
    cur.execute("""
        UPDATE camera
        SET
            camera_name = '',
            camera_ip = '',
            camera_port = 554,
            camera_username = '',
            camera_password = '',
            rtsp_path = ''
    """)

    conn.commit()
    conn.close()

    return {
        "ok": True
    }