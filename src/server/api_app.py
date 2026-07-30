import os
import sqlite3
from typing import Any

from flask import (
    Flask,
    jsonify,
    request,
)
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from src.logger import create_logger
from src.server.config import (
    API_KEY_USING_DEFAULT,
    ensure_runtime_directories,
)
from src.server.init_db import ensure_database
from src.server.routes.calibration_routes import (
    calibration_bp,
)
from src.server.routes.camera_routes import (
    camera_bp,
)
from src.server.routes.history_routes import (
    history_bp,
)
from src.server.routes.system_routes import (
    system_bp,
)
from src.server.routes.tag_routes import (
    tag_bp,
)
from src.server.routes.worker_routes import (
    worker_bp,
)


logger = create_logger(
    "server.api_app"
)


DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 5001

DEFAULT_MAX_REQUEST_BYTES = (
    8 * 1024 * 1024
)

MIN_MAX_REQUEST_BYTES = (
    64 * 1024
)

MAX_MAX_REQUEST_BYTES = (
    100 * 1024 * 1024
)


BLUEPRINTS = (
    system_bp,
    camera_bp,
    calibration_bp,
    history_bp,
    tag_bp,
    worker_bp,
)


_HTTP_ERROR_MESSAGES = {
    400: "Invalid request",
    401: "Authentication is required",
    403: "Access is forbidden",
    404: "API endpoint not found",
    405: "Method is not allowed",
    408: "Request timed out",
    409: "Request conflicts with current data",
    413: "Request body is too large",
    415: "Unsupported media type",
    422: "Request data could not be processed",
    429: "Too many requests",
    500: "Internal API server error",
    502: "Upstream service error",
    503: "API service is temporarily unavailable",
    504: "Upstream service timed out",
}


def _get_environment_int(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = os.getenv(
        name
    )

    if raw_value is None:
        return default

    try:
        value = int(
            raw_value.strip()
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        logger.warning(
            (
                "Invalid integer environment "
                "variable: name=%s"
            ),
            name,
        )

        return default

    return max(
        minimum,
        min(
            value,
            maximum,
        ),
    )


def _get_api_port() -> int:
    return _get_environment_int(
        "API_PORT",
        DEFAULT_API_PORT,
        1,
        65535,
    )


def _get_max_request_bytes() -> int:
    return _get_environment_int(
        "API_MAX_REQUEST_BYTES",
        DEFAULT_MAX_REQUEST_BYTES,
        MIN_MAX_REQUEST_BYTES,
        MAX_MAX_REQUEST_BYTES,
    )


def _get_api_host() -> str:
    host = os.getenv(
        "API_HOST",
        DEFAULT_API_HOST,
    ).strip()

    return (
        host
        or DEFAULT_API_HOST
    )


def _get_cors_origins() -> list[str]:
    """
    CORS is disabled unless API_CORS_ORIGINS
    is explicitly configured.

    Example:
        API_CORS_ORIGINS=http://localhost:5000
        API_CORS_ORIGINS=https://example.com
    """
    raw_value = os.getenv(
        "API_CORS_ORIGINS",
        "",
    ).strip()

    if not raw_value:
        return []

    origins = []

    for item in raw_value.split(
        ","
    ):
        origin = item.strip()

        if not origin:
            continue

        if (
            "\r" in origin
            or "\n" in origin
            or "\x00" in origin
        ):
            logger.warning(
                (
                    "Invalid CORS origin "
                    "was ignored"
                )
            )

            continue

        origins.append(
            origin[:2048]
        )

    return list(
        dict.fromkeys(
            origins
        )
    )


def _client_address() -> str:
    address = request.remote_addr

    if not address:
        return "unknown"

    return str(
        address
    )[:100]


def _request_path() -> str:
    try:
        return str(
            request.path
        )[:1000]

    except Exception:
        return "unknown"


def _error_response(
    message: str,
    status_code: int,
):
    response = jsonify({
        "ok": False,
        "message": message,
    })

    response.status_code = (
        status_code
    )

    response.headers[
        "Cache-Control"
    ] = "no-store"

    return response


def _database_is_busy(
    error: BaseException,
) -> bool:
    message = str(
        error
    ).casefold()

    return (
        "locked" in message
        or "busy" in message
    )


def _configure_cors(
    app: Flask,
) -> None:
    origins = _get_cors_origins()

    if not origins:
        logger.info(
            (
                "API CORS is disabled; "
                "Web access should use "
                "the internal proxy"
            )
        )

        return

    CORS(
        app,
        resources={
            r"/api/*": {
                "origins": origins,
            },
        },
        methods=[
            "GET",
            "POST",
            "OPTIONS",
        ],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
        ],
        expose_headers=[
            "Content-Type",
        ],
        supports_credentials=False,
        max_age=600,
    )

    logger.info(
        (
            "API CORS enabled for "
            "%d configured origin(s)"
        ),
        len(
            origins
        ),
    )


def _register_blueprints(
    app: Flask,
) -> None:
    for blueprint in BLUEPRINTS:
        app.register_blueprint(
            blueprint
        )


def _register_response_headers(
    app: Flask,
) -> None:
    @app.after_request
    def add_security_headers(
        response,
    ):
        response.headers.setdefault(
            "Cache-Control",
            "no-store",
        )

        response.headers.setdefault(
            "X-Content-Type-Options",
            "nosniff",
        )

        response.headers.setdefault(
            "X-Frame-Options",
            "DENY",
        )

        response.headers.setdefault(
            "Referrer-Policy",
            "no-referrer",
        )

        response.headers.setdefault(
            "Cross-Origin-Resource-Policy",
            "same-origin",
        )

        response.headers.setdefault(
            "Content-Security-Policy",
            (
                "default-src 'none'; "
                "frame-ancestors 'none'"
            ),
        )

        return response


def _register_error_handlers(
    app: Flask,
) -> None:
    @app.errorhandler(
        sqlite3.OperationalError
    )
    def handle_database_operation_error(
        error,
    ):
        if _database_is_busy(
            error
        ):
            logger.warning(
                (
                    "API request delayed because "
                    "the database is busy: "
                    "method=%s, path=%s, client=%s"
                ),
                request.method,
                _request_path(),
                _client_address(),
            )

            return _error_response(
                (
                    "Database is temporarily "
                    "busy. Please try again."
                ),
                503,
            )

        logger.exception(
            (
                "Unhandled database operation "
                "error: method=%s, path=%s"
            ),
            request.method,
            _request_path(),
        )

        return _error_response(
            "Database operation failed",
            500,
        )

    @app.errorhandler(
        sqlite3.Error
    )
    def handle_database_error(
        _error,
    ):
        logger.exception(
            (
                "Unhandled database error: "
                "method=%s, path=%s"
            ),
            request.method,
            _request_path(),
        )

        return _error_response(
            "Database operation failed",
            500,
        )

    @app.errorhandler(
        HTTPException
    )
    def handle_http_error(
        error,
    ):
        status_code = int(
            error.code
            or 500
        )

        message = (
            _HTTP_ERROR_MESSAGES.get(
                status_code,
                (
                    "Request could not "
                    "be completed"
                ),
            )
        )

        if status_code == 404:
            logger.debug(
                (
                    "API endpoint not found: "
                    "method=%s, path=%s, client=%s"
                ),
                request.method,
                _request_path(),
                _client_address(),
            )

        elif status_code >= 500:
            logger.error(
                (
                    "API HTTP server error: "
                    "status=%s, method=%s, "
                    "path=%s"
                ),
                status_code,
                request.method,
                _request_path(),
            )

        else:
            logger.warning(
                (
                    "API request rejected: "
                    "status=%s, method=%s, "
                    "path=%s, client=%s"
                ),
                status_code,
                request.method,
                _request_path(),
                _client_address(),
            )

        return _error_response(
            message,
            status_code,
        )

    @app.errorhandler(
        Exception
    )
    def handle_unexpected_error(
        _error,
    ):
        logger.exception(
            (
                "Unhandled API server error: "
                "method=%s, path=%s, client=%s"
            ),
            request.method,
            _request_path(),
            _client_address(),
        )

        return _error_response(
            "Internal API server error",
            500,
        )


def _initialize_runtime() -> None:
    """
    Validate runtime directories and initialize
    the database before accepting requests.
    """
    ensure_runtime_directories(
        strict=True
    )

    ensure_database()


def create_app() -> Flask:
    """
    Create and configure the API server.
    """
    logger.info(
        "Starting API server initialization"
    )

    try:
        _initialize_runtime()

    except Exception:
        logger.exception(
            (
                "API server runtime "
                "initialization failed"
            )
        )

        raise

    app = Flask(
        __name__
    )

    app.config.update(
        MAX_CONTENT_LENGTH=(
            _get_max_request_bytes()
        ),
        JSON_SORT_KEYS=False,
        PROPAGATE_EXCEPTIONS=False,
    )

    _register_response_headers(
        app
    )

    _register_error_handlers(
        app
    )

    _configure_cors(
        app
    )

    _register_blueprints(
        app
    )

    if API_KEY_USING_DEFAULT:
        logger.warning(
            (
                "API server is using the "
                "default development API key. "
                "Set API_KEY before production use."
            )
        )

    logger.info(
        (
            "API server initialization "
            "completed"
        )
    )

    return app


app = create_app()


if __name__ == "__main__":
    host = _get_api_host()
    port = _get_api_port()

    logger.info(
        (
            "API server is starting: "
            "host=%s, port=%d"
        ),
        host,
        port,
    )

    try:
        app.run(
            host=host,
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )

    except Exception:
        logger.exception(
            (
                "API server stopped "
                "unexpectedly"
            )
        )

        raise