from collections import deque
from pathlib import Path

from flask import (
    Blueprint,
    jsonify,
    request,
)

from src.logger import create_logger
from src.server.auth import require_api_key


logger = create_logger(
    "server.routes.system"
)


system_bp = Blueprint(
    "system",
    __name__,
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[3]
)

LOG_FILE_PATH = (
    PROJECT_ROOT
    / "logs"
    / "app_log.txt"
)

DEFAULT_LOG_LINES = 500
MAX_LOG_LINES = 2000


def read_last_log_lines(
    file_path,
    line_count,
):
    """
    Read only the latest lines from a log file.

    deque prevents the entire log file from being
    stored in memory when the file becomes large.
    """
    with file_path.open(
        mode="r",
        encoding="utf-8",
        errors="replace",
    ) as log_file:
        return [
            line.rstrip("\r\n")
            for line in deque(
                log_file,
                maxlen=line_count,
            )
        ]


@system_bp.route(
    "/api/health",
    methods=["GET"],
)
def api_health():
    try:
        logger.info(
            "Health check requested"
        )

        return jsonify({
            "ok": True,
            "message": (
                "API server is running"
            ),
        })

    except Exception:
        logger.exception(
            "Health check failed"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Health check failed"
            ),
        }), 500


@system_bp.route(
    "/api/system/logs",
    methods=["GET"],
)
@require_api_key
def api_system_logs():
    """
    Return the latest application log lines.

    Example:
    /api/system/logs?lines=500
    """
    requested_lines = request.args.get(
        "lines",
        default=DEFAULT_LOG_LINES,
        type=int,
    )

    if requested_lines is None:
        requested_lines = (
            DEFAULT_LOG_LINES
        )

    line_count = max(
        1,
        min(
            requested_lines,
            MAX_LOG_LINES,
        ),
    )

    try:
        if not LOG_FILE_PATH.exists():
            return jsonify({
                "ok": True,
                "exists": False,
                "count": 0,
                "lines": [],
                "message": (
                    "No log data found"
                ),
            })

        if not LOG_FILE_PATH.is_file():
            logger.error(
                "Application log path "
                "is not a file"
            )

            return jsonify({
                "ok": False,
                "message": (
                    "Application log is unavailable"
                ),
            }), 500

        lines = read_last_log_lines(
            file_path=LOG_FILE_PATH,
            line_count=line_count,
        )

        return jsonify({
            "ok": True,
            "exists": True,
            "count": len(lines),
            "requested_lines": (
                line_count
            ),
            "maximum_lines": (
                MAX_LOG_LINES
            ),
            "lines": lines,
        })

    except FileNotFoundError:
        # กรณีไฟล์ถูกหมุนหรือลบในจังหวะ
        # ระหว่างตรวจสอบและเปิดอ่าน
        return jsonify({
            "ok": True,
            "exists": False,
            "count": 0,
            "lines": [],
            "message": (
                "No log data found"
            ),
        })

    except PermissionError:
        logger.exception(
            "Permission denied while "
            "reading application log"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Application log cannot "
                "be accessed"
            ),
        }), 500

    except OSError:
        logger.exception(
            "Failed to read application log"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Application log cannot "
                "be read"
            ),
        }), 500

    except Exception:
        logger.exception(
            "Unexpected log viewer error"
        )

        return jsonify({
            "ok": False,
            "message": (
                "Failed to load application log"
            ),
        }), 500