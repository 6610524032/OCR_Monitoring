import sqlite3
from collections.abc import Mapping
from functools import wraps
from typing import Any, Callable

from flask import (
    Blueprint,
    jsonify,
    request,
)

from src.logger import create_logger
from src.server.auth import require_api_key
from src.server.repositories.history_repository import (
    get_abnormal_history_runs,
    get_history_data,
    get_history_run_detail,
    get_history_variables,
    get_latest_log,
)


logger = create_logger(
    "server.routes.history"
)


history_bp = Blueprint(
    "history",
    __name__,
)


DEFAULT_HISTORY_DAYS = 2
MAX_HISTORY_DAYS = 365
MAX_TAG_NAME_LENGTH = 150


class HistoryRouteValidationError(
    ValueError
):
    """
    Raised when a History API parameter
    is invalid.
    """


def _error_response(
    message: str,
    status_code: int,
):
    return jsonify({
        "ok": False,
        "message": message,
    }), status_code


def _database_is_busy(
    error: BaseException,
) -> bool:
    error_text = str(
        error
    ).casefold()

    return (
        "locked" in error_text
        or "busy" in error_text
    )


def _handle_history_errors(
    operation: str,
    public_message: str,
):
    """
    Convert History validation and database
    errors into consistent HTTP responses.
    """

    def decorator(
        function: Callable,
    ):
        @wraps(
            function
        )
        def wrapper(
            *args,
            **kwargs,
        ):
            try:
                return function(
                    *args,
                    **kwargs,
                )

            except HistoryRouteValidationError as error:
                logger.warning(
                    "%s rejected: %s",
                    operation,
                    error,
                )

                return _error_response(
                    str(
                        error
                    ),
                    400,
                )

            except sqlite3.OperationalError as error:
                if _database_is_busy(
                    error
                ):
                    logger.warning(
                        (
                            "%s delayed because "
                            "the database is busy"
                        ),
                        operation,
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
                        "%s failed because of "
                        "a database operation"
                    ),
                    operation,
                )

                return _error_response(
                    public_message,
                    500,
                )

            except sqlite3.Error:
                logger.exception(
                    (
                        "%s failed because of "
                        "a database error"
                    ),
                    operation,
                )

                return _error_response(
                    public_message,
                    500,
                )

            except Exception:
                logger.exception(
                    "%s failed unexpectedly",
                    operation,
                )

                return _error_response(
                    public_message,
                    500,
                )

        return wrapper

    return decorator


def _as_list(
    value: Any,
    field_name: str,
) -> list:
    if value is None:
        return []

    if isinstance(
        value,
        list,
    ):
        return value

    if isinstance(
        value,
        tuple,
    ):
        return list(
            value
        )

    raise RuntimeError(
        (
            f"{field_name} must be "
            "returned as a list"
        )
    )


def _as_mapping(
    value: Any,
    field_name: str,
) -> dict:
    if isinstance(
        value,
        Mapping,
    ):
        return dict(
            value
        )

    try:
        return dict(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as error:
        raise RuntimeError(
            (
                f"{field_name} must be "
                "returned as an object"
            )
        ) from error


def _read_tag_name() -> str:
    tag_name = request.args.get(
        "tag_name",
        "",
    )

    if not isinstance(
        tag_name,
        str,
    ):
        raise HistoryRouteValidationError(
            "tag_name must be a string"
        )

    tag_name = tag_name.strip()

    if not tag_name:
        raise HistoryRouteValidationError(
            "tag_name is required"
        )

    if "\x00" in tag_name:
        raise HistoryRouteValidationError(
            (
                "tag_name contains an "
                "invalid character"
            )
        )

    if (
        len(
            tag_name
        )
        > MAX_TAG_NAME_LENGTH
    ):
        raise HistoryRouteValidationError(
            "tag_name is too long"
        )

    return tag_name


def _read_history_days() -> int:
    raw_days = request.args.get(
        "days"
    )

    if raw_days in (
        None,
        "",
    ):
        return DEFAULT_HISTORY_DAYS

    try:
        days = int(
            raw_days
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise HistoryRouteValidationError(
            "days must be an integer"
        ) from error

    if days <= 0:
        raise HistoryRouteValidationError(
            (
                "days must be greater "
                "than zero"
            )
        )

    if days > MAX_HISTORY_DAYS:
        raise HistoryRouteValidationError(
            (
                f"days must not exceed "
                f"{MAX_HISTORY_DAYS}"
            )
        )

    return days


@history_bp.route(
    "/api/latest",
    methods=["GET"],
)
@require_api_key
@_handle_history_errors(
    "Latest OCR data load",
    "Failed to load latest OCR data",
)
def api_latest():
    latest = get_latest_log()

    if latest is None:
        logger.debug(
            (
                "No latest OCR data "
                "is available"
            )
        )

        return jsonify({
            "ok": True,
            "has_data": False,
            "message": "No OCR data found",
            "data": None,
        })

    latest_data = _as_mapping(
        latest,
        "latest OCR data",
    )

    logger.debug(
        (
            "Latest OCR data loaded: "
            "run_id=%s"
        ),
        latest_data.get(
            "id",
            latest_data.get(
                "run_id"
            ),
        ),
    )

    return jsonify({
        "ok": True,
        "has_data": True,
        "data": latest_data,
    })


@history_bp.route(
    "/api/history/alerts",
    methods=["GET"],
)
@require_api_key
@_handle_history_errors(
    "Abnormal History load",
    "Failed to load abnormal history",
)
def api_history_alerts():
    items = _as_list(
        get_abnormal_history_runs(),
        "abnormal history",
    )

    logger.debug(
        (
            "Abnormal History loaded: "
            "count=%d"
        ),
        len(
            items
        ),
    )

    return jsonify({
        "ok": True,
        "count": len(
            items
        ),
        "items": items,
    })


@history_bp.route(
    "/api/history/variables",
    methods=["GET"],
)
@require_api_key
@_handle_history_errors(
    "History variables load",
    "Failed to load history variables",
)
def api_history_variables():
    variables = _as_list(
        get_history_variables(),
        "history variables",
    )

    logger.debug(
        (
            "History variables loaded: "
            "count=%d"
        ),
        len(
            variables
        ),
    )

    return jsonify({
        "ok": True,
        "variables": variables,
    })


@history_bp.route(
    "/api/history/data",
    methods=["GET"],
)
@require_api_key
@_handle_history_errors(
    "History chart data load",
    "Failed to load history data",
)
def api_history_data():
    tag_name = _read_tag_name()
    days = _read_history_days()

    points = _as_list(
        get_history_data(
            tag_name=tag_name,
            days=days,
        ),
        "history points",
    )

    logger.debug(
        (
            "History chart data loaded: "
            "tag_name=%s, days=%d, "
            "point_count=%d"
        ),
        tag_name,
        days,
        len(
            points
        ),
    )

    return jsonify({
        "ok": True,
        "tag_name": tag_name,
        "days": days,
        "points": points,
    })


@history_bp.route(
    "/api/history/run/<int:run_id>",
    methods=["GET"],
)
@require_api_key
@_handle_history_errors(
    "History run detail load",
    "Failed to load history run",
)
def api_history_run(
    run_id,
):
    if run_id <= 0:
        raise HistoryRouteValidationError(
            (
                "run_id must be greater "
                "than zero"
            )
        )

    detail = get_history_run_detail(
        run_id
    )

    if detail is None:
        logger.debug(
            (
                "History run was not "
                "found: run_id=%s"
            ),
            run_id,
        )

        return _error_response(
            "Run not found",
            404,
        )

    detail_data = _as_mapping(
        detail,
        "history run detail",
    )

    if "run" not in detail_data:
        raise RuntimeError(
            (
                "History run detail does "
                "not contain run data"
            )
        )

    run_data = _as_mapping(
        detail_data.get(
            "run"
        ),
        "history run",
    )

    values = _as_list(
        detail_data.get(
            "values",
            [],
        ),
        "history values",
    )

    logger.debug(
        (
            "History run loaded: "
            "run_id=%s, value_count=%d"
        ),
        run_id,
        len(
            values
        ),
    )

    return jsonify({
        "ok": True,
        "run": run_data,
        "values": values,
    })