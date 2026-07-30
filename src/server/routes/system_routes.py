import re
from pathlib import Path
from typing import Any

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

LOG_DIRECTORY = (
    PROJECT_ROOT
    / "logs"
)

LOG_FILE_PATH = (
    LOG_DIRECTORY
    / "app_log.txt"
)


DEFAULT_LOG_LINES = 500
MAX_LOG_LINES = 2000

LOG_READ_BLOCK_SIZE = 64 * 1024
MAX_LOG_READ_BYTES = 2 * 1024 * 1024
MAX_LOG_LINE_LENGTH = 10_000


_SECRET_PATTERNS = (
    re.compile(
        (
            r"(?i)"
            r"(Authorization\s*[:=]\s*"
            r"Bearer\s+)"
            r"([^\s,;]+)"
        )
    ),
    re.compile(
        (
            r"(?i)"
            r"(rtsp://[^:/@\s]+:)"
            r"([^@\s]+)"
            r"(@)"
        )
    ),
    re.compile(
        (
            r"(?i)"
            r"("
            r"[\"']?"
            r"(?:"
            r"password"
            r"|camera_password"
            r"|api_key"
            r"|apikey"
            r"|sensor_api_key"
            r"|access_token"
            r"|token"
            r"|secret"
            r")"
            r"[\"']?"
            r"\s*[:=]\s*"
            r"[\"']?"
            r")"
            r"([^\"',}\s]+)"
        )
    ),
)


class SystemRouteValidationError(
    ValueError
):
    """
    Raised when a System API parameter
    is invalid.
    """


def _json_response(
    payload: dict[str, Any],
    status_code: int = 200,
):
    response = jsonify(
        payload
    )

    response.status_code = (
        status_code
    )

    response.headers[
        "Cache-Control"
    ] = (
        "no-store, no-cache, "
        "must-revalidate, max-age=0"
    )

    response.headers[
        "Pragma"
    ] = "no-cache"

    return response


def _read_requested_line_count() -> int:
    raw_value = request.args.get(
        "lines"
    )

    if raw_value in (
        None,
        "",
    ):
        return DEFAULT_LOG_LINES

    try:
        line_count = int(
            raw_value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise SystemRouteValidationError(
            "lines must be an integer"
        ) from error

    if line_count <= 0:
        raise SystemRouteValidationError(
            (
                "lines must be greater "
                "than zero"
            )
        )

    return min(
        line_count,
        MAX_LOG_LINES,
    )


def _redact_log_line(
    line: str,
) -> str:
    """
    Hide common credentials before log
    content is returned to the browser.
    """
    redacted = line

    redacted = (
        _SECRET_PATTERNS[0].sub(
            r"\1[REDACTED]",
            redacted,
        )
    )

    redacted = (
        _SECRET_PATTERNS[1].sub(
            r"\1[REDACTED]\3",
            redacted,
        )
    )

    redacted = (
        _SECRET_PATTERNS[2].sub(
            r"\1[REDACTED]",
            redacted,
        )
    )

    if (
        len(
            redacted
        )
        > MAX_LOG_LINE_LENGTH
    ):
        redacted = (
            redacted[
                :MAX_LOG_LINE_LENGTH
            ]
            + " ... [LINE TRUNCATED]"
        )

    return redacted


def read_last_log_lines(
    file_path: Path,
    line_count: int,
) -> tuple[
    list[str],
    int,
    int,
    bool,
]:
    """
    Read the end of a log file without scanning
    the complete file on every request.

    Returns:
        lines
        file_size
        bytes_read
        truncated
    """
    with file_path.open(
        mode="rb"
    ) as log_file:
        log_file.seek(
            0,
            2,
        )

        file_size = (
            log_file.tell()
        )

        position = file_size
        chunks = []
        bytes_read = 0
        newline_count = 0

        while (
            position > 0
            and newline_count
            <= line_count
            and bytes_read
            < MAX_LOG_READ_BYTES
        ):
            remaining_limit = (
                MAX_LOG_READ_BYTES
                - bytes_read
            )

            read_size = min(
                LOG_READ_BLOCK_SIZE,
                position,
                remaining_limit,
            )

            if read_size <= 0:
                break

            position -= read_size

            log_file.seek(
                position
            )

            chunk = log_file.read(
                read_size
            )

            if not chunk:
                break

            chunks.append(
                chunk
            )

            bytes_read += len(
                chunk
            )

            newline_count += (
                chunk.count(
                    b"\n"
                )
            )

        raw_content = b"".join(
            reversed(
                chunks
            )
        )

    decoded_content = (
        raw_content.decode(
            "utf-8",
            errors="replace",
        )
    )

    raw_lines = (
        decoded_content.splitlines()
    )

    selected_lines = raw_lines[
        -line_count:
    ]

    lines = [
        _redact_log_line(
            line
        )
        for line in selected_lines
    ]

    truncated = (
        position > 0
        or len(
            raw_lines
        )
        > line_count
    )

    return (
        lines,
        file_size,
        bytes_read,
        truncated,
    )


@system_bp.route(
    "/api/health",
    methods=["GET"],
)
def api_health():
    """
    Lightweight health endpoint.

    This route intentionally does not access
    the database, camera, or OCR model.
    """
    return _json_response({
        "ok": True,
        "status": "healthy",
        "message": (
            "API server is running"
        ),
    })


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
    try:
        line_count = (
            _read_requested_line_count()
        )

    except SystemRouteValidationError as error:
        logger.warning(
            (
                "Log viewer request "
                "rejected: %s"
            ),
            error,
        )

        return _json_response(
            {
                "ok": False,
                "message": str(
                    error
                ),
            },
            400,
        )

    try:
        if not LOG_FILE_PATH.exists():
            return _json_response({
                "ok": True,
                "exists": False,
                "count": 0,
                "requested_lines": (
                    line_count
                ),
                "maximum_lines": (
                    MAX_LOG_LINES
                ),
                "lines": [],
                "message": (
                    "No log data found"
                ),
            })

        if not LOG_FILE_PATH.is_file():
            logger.error(
                (
                    "Application log path "
                    "is not a file"
                )
            )

            return _json_response(
                {
                    "ok": False,
                    "message": (
                        "Application log "
                        "is unavailable"
                    ),
                },
                500,
            )

        (
            lines,
            file_size,
            bytes_read,
            truncated,
        ) = read_last_log_lines(
            file_path=LOG_FILE_PATH,
            line_count=line_count,
        )

        logger.debug(
            (
                "Application log tail "
                "loaded: lines=%d, "
                "bytes_read=%d"
            ),
            len(
                lines
            ),
            bytes_read,
        )

        return _json_response({
            "ok": True,
            "exists": True,
            "count": len(
                lines
            ),
            "requested_lines": (
                line_count
            ),
            "maximum_lines": (
                MAX_LOG_LINES
            ),
            "file_size_bytes": (
                file_size
            ),
            "bytes_read": bytes_read,
            "truncated": truncated,
            "lines": lines,
        })

    except FileNotFoundError:
        # ไฟล์อาจถูกหมุนหรือลบหลังจาก
        # exists() แต่ก่อน open()
        return _json_response({
            "ok": True,
            "exists": False,
            "count": 0,
            "requested_lines": (
                line_count
            ),
            "maximum_lines": (
                MAX_LOG_LINES
            ),
            "lines": [],
            "message": (
                "No log data found"
            ),
        })

    except PermissionError:
        logger.error(
            (
                "Permission denied while "
                "reading application log"
            )
        )

        return _json_response(
            {
                "ok": False,
                "message": (
                    "Application log "
                    "cannot be accessed"
                ),
            },
            500,
        )

    except OSError:
        logger.exception(
            (
                "Operating-system error "
                "while reading application log"
            )
        )

        return _json_response(
            {
                "ok": False,
                "message": (
                    "Application log "
                    "cannot be read"
                ),
            },
            500,
        )

    except Exception:
        logger.exception(
            (
                "Unexpected log "
                "viewer error"
            )
        )

        return _json_response(
            {
                "ok": False,
                "message": (
                    "Failed to load "
                    "application log"
                ),
            },
            500,
        )