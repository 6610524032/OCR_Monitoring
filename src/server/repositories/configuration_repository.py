from src.logger import create_logger
from src.server.database import get_connection


logger = create_logger(
    "server.repositories.configuration"
)


def reset_configuration_data():
    conn = get_connection()
    cur = conn.cursor()

    try:
        logger.info(
            "Resetting system configuration"
        )

        # Reset calibration
        cur.execute(
            "DELETE FROM calibration"
        )

        # Reset user tags
        cur.execute(
            "DELETE FROM user_tags"
        )

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

        logger.info(
            "System configuration reset successfully"
        )

        return {
            "ok": True
        }

    except Exception:
        conn.rollback()

        logger.exception(
            "Failed to reset system configuration"
        )

        raise

    finally:
        conn.close()