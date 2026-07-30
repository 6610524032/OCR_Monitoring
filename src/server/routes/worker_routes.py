import math
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from functools import wraps
from typing import Any, Callable

from flask import Blueprint, jsonify, request

from src.logger import create_logger
from src.processing.ocr.model_status import (
    OCRModelStatus,
    read_model_status_file,
)
from src.processing.ocr.service import read_manual_roi
from src.server.auth import require_api_key
from src.server.repositories.calibration_repository import (
    get_active_calibration,
)
from src.server.repositories.configuration_repository import (
    reset_configuration_data,
)
from src.server.repositories.ocr_repository import (
    save_worker_ocr_run,
)
from src.server.repositories.queue_repository import (
    claim_pending_queue,
    create_queue_items,
    mark_queue_failed,
    mark_queue_sent,
)
from src.server.repositories.tag_repository import (
    get_active_user_tags,
)


logger = create_logger(
    "server.routes.worker"
)


worker_bp = Blueprint(
    "worker",
    __name__,
)


MAX_PATH_LENGTH = 2048
MAX_TEXT_LENGTH = 2000
MAX_QUEUE_IDS = 5000
MAX_CLAIM_LIMIT = 1000


class WorkerRouteValidationError(
    ValueError
):
    """
    Raised when a Worker API payload
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


def _handle_route_errors(
    operation: str,
    public_message: str,
):
    """
    Convert validation and database errors
    into consistent API responses.
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

            except WorkerRouteValidationError as error:
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

            except ValueError as error:
                logger.warning(
                    (
                        "%s rejected by "
                        "repository: %s"
                    ),
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
                            "database is busy"
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


def _read_json_object(
    required: bool = True,
) -> Mapping[str, Any]:
    raw_body = request.get_data(
        cache=True
    )

    if not raw_body:
        if required:
            raise WorkerRouteValidationError(
                "JSON request body is required"
            )

        return {}

    if not request.is_json:
        raise WorkerRouteValidationError(
            (
                "Request body must use "
                "application/json"
            )
        )

    data = request.get_json(
        silent=True
    )

    if not isinstance(
        data,
        Mapping,
    ):
        raise WorkerRouteValidationError(
            (
                "Request body must contain "
                "a valid JSON object"
            )
        )

    return data


def _required_text(
    value: Any,
    field_name: str,
    max_length: int = MAX_TEXT_LENGTH,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise WorkerRouteValidationError(
            (
                f"{field_name} must "
                "be a string"
            )
        )

    normalized = value.strip()

    if not normalized:
        raise WorkerRouteValidationError(
            f"{field_name} is required"
        )

    if "\x00" in normalized:
        raise WorkerRouteValidationError(
            (
                f"{field_name} contains "
                "an invalid character"
            )
        )

    if len(
        normalized
    ) > max_length:
        raise WorkerRouteValidationError(
            f"{field_name} is too long"
        )

    return normalized


def _optional_text(
    value: Any,
    field_name: str,
    max_length: int = MAX_TEXT_LENGTH,
) -> str:
    if value is None:
        return ""

    normalized = str(
        value
    ).strip()

    if "\x00" in normalized:
        raise WorkerRouteValidationError(
            (
                f"{field_name} contains "
                "an invalid character"
            )
        )

    return normalized[
        :max_length
    ]


def _positive_integer(
    value: Any,
    field_name: str,
    maximum: int | None = None,
) -> int:
    if isinstance(
        value,
        bool,
    ):
        raise WorkerRouteValidationError(
            (
                f"{field_name} must "
                "be an integer"
            )
        )

    if (
        isinstance(
            value,
            float,
        )
        and not value.is_integer()
    ):
        raise WorkerRouteValidationError(
            (
                f"{field_name} must "
                "be an integer"
            )
        )

    try:
        parsed = int(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise WorkerRouteValidationError(
            (
                f"{field_name} must "
                "be an integer"
            )
        ) from error

    if parsed <= 0:
        raise WorkerRouteValidationError(
            (
                f"{field_name} must be "
                "greater than zero"
            )
        )

    if (
        maximum is not None
        and parsed > maximum
    ):
        raise WorkerRouteValidationError(
            (
                f"{field_name} must not "
                f"exceed {maximum}"
            )
        )

    return parsed


def _finite_number(
    value: Any,
    field_name: str,
) -> float:
    if isinstance(
        value,
        bool,
    ):
        raise WorkerRouteValidationError(
            f"{field_name} must be numeric"
        )

    try:
        parsed = float(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise WorkerRouteValidationError(
            f"{field_name} must be numeric"
        ) from error

    if not math.isfinite(
        parsed
    ):
        raise WorkerRouteValidationError(
            f"{field_name} must be finite"
        )

    return parsed


def _optional_http_status(
    value: Any,
) -> int | None:
    if value in (
        None,
        "",
    ):
        return None

    status_code = _positive_integer(
        value,
        "http_status",
    )

    if not 100 <= status_code <= 599:
        raise WorkerRouteValidationError(
            (
                "http_status must be "
                "between 100 and 599"
            )
        )

    return status_code


def _parse_queue_ids(
    value: Any,
) -> list[int]:
    if not isinstance(
        value,
        list,
    ):
        raise WorkerRouteValidationError(
            "queue_ids must be a list"
        )

    if not value:
        raise WorkerRouteValidationError(
            "queue_ids cannot be empty"
        )

    if len(
        value
    ) > MAX_QUEUE_IDS:
        raise WorkerRouteValidationError(
            (
                "queue_ids contains too "
                "many items"
            )
        )

    queue_ids = []
    seen_ids = set()

    for index, raw_id in enumerate(
        value
    ):
        queue_id = _positive_integer(
            raw_id,
            f"queue_ids[{index}]",
        )

        if queue_id in seen_ids:
            continue

        seen_ids.add(
            queue_id
        )

        queue_ids.append(
            queue_id
        )

    return queue_ids


def _manual_ocr_failure_status(
    message: str,
) -> int:
    normalized = message.casefold()

    if "not found" in normalized:
        return 404

    if (
        "cannot read image" in normalized
        or "cannot decode" in normalized
    ):
        return 422

    if (
        "invalid" in normalized
        or "empty roi" in normalized
        or "image name" in normalized
        or "image path" in normalized
    ):
        return 400

    return 500


@worker_bp.route(
    "/api/read_manual_roi",
    methods=["POST"],
)
@require_api_key
@_handle_route_errors(
    "Manual OCR request",
    "Manual OCR failed",
)
def api_read_manual_roi():
    data = _read_json_object()

    image_name = _required_text(
        data.get(
            "image"
        ),
        "image",
        MAX_PATH_LENGTH,
    )

    x1 = _finite_number(
        data.get(
            "x1"
        ),
        "x1",
    )

    y1 = _finite_number(
        data.get(
            "y1"
        ),
        "y1",
    )

    x2 = _finite_number(
        data.get(
            "x2"
        ),
        "x2",
    )

    y2 = _finite_number(
        data.get(
            "y2"
        ),
        "y2",
    )

    if x2 <= x1:
        raise WorkerRouteValidationError(
            "x2 must be greater than x1"
        )

    if y2 <= y1:
        raise WorkerRouteValidationError(
            "y2 must be greater than y1"
        )

    model_status = (
        read_model_status_file()
    )

    current_status = str(
        model_status.get(
            "status",
            OCRModelStatus.NOT_STARTED.value,
        )
    ).strip().casefold()

    if (
        current_status
        != OCRModelStatus.READY.value
    ):
        response_status = (
            "error"
            if current_status
            == OCRModelStatus.ERROR.value
            else "loading"
        )

        message = _optional_text(
            model_status.get(
                "message",
                "OCR model is not ready",
            ),
            "model_status.message",
            500,
        ) or "OCR model is not ready"

        logger.debug(
            (
                "Manual OCR deferred because "
                "model status is %s"
            ),
            current_status,
        )

        response = jsonify({
            "ok": False,
            "status": response_status,
            "message": message,
        })

        response.status_code = 503

        response.headers[
            "Retry-After"
        ] = "5"

        return response

    result = read_manual_roi(
        image_name=image_name,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
    )

    if not isinstance(
        result,
        Mapping,
    ):
        logger.error(
            (
                "Manual OCR returned "
                "an invalid result"
            )
        )

        return _error_response(
            (
                "Manual OCR returned "
                "an invalid result"
            ),
            500,
        )

    result = dict(
        result
    )

    if result.get(
        "ok"
    ):
        logger.info(
            (
                "Manual OCR completed: "
                "value_found=%s"
            ),
            bool(
                result.get(
                    "text",
                    result.get(
                        "value",
                        "",
                    ),
                )
            ),
        )

        return jsonify(
            result
        )

    message = _optional_text(
        result.get(
            "message",
            "Manual OCR failed",
        ),
        "message",
        500,
    ) or "Manual OCR failed"

    status_code = (
        _manual_ocr_failure_status(
            message
        )
    )

    if status_code >= 500:
        logger.error(
            "Manual OCR failed: %s",
            message,
        )

    else:
        logger.warning(
            (
                "Manual OCR was not "
                "completed: %s"
            ),
            message,
        )

    return jsonify(
        result
    ), status_code


@worker_bp.route(
    "/api/reset_configuration",
    methods=["POST"],
)
@require_api_key
@_handle_route_errors(
    "Configuration reset",
    "Cannot reset configuration",
)
def api_reset_configuration():
    result = (
        reset_configuration_data()
    )

    if not isinstance(
        result,
        Mapping,
    ):
        logger.error(
            (
                "Configuration repository "
                "returned an invalid result"
            )
        )

        return _error_response(
            (
                "Configuration reset returned "
                "an invalid result"
            ),
            500,
        )

    result = dict(
        result
    )

    if result.get(
        "ok"
    ):
        logger.info(
            (
                "Configuration reset "
                "completed"
            )
        )

        return jsonify(
            result
        )

    logger.warning(
        (
            "Configuration reset did "
            "not complete"
        )
    )

    return jsonify(
        result
    ), 400


@worker_bp.route(
    "/api/worker/config",
    methods=["GET"],
)
@require_api_key
@_handle_route_errors(
    "Worker configuration load",
    "Cannot load worker configuration",
)
def api_worker_config():
    calibration = (
        get_active_calibration()
    )

    tags = (
        get_active_user_tags()
    )

    if tags is None:
        tags = []

    elif not isinstance(
        tags,
        list,
    ):
        tags = list(
            tags
        )

    logger.debug(
        (
            "Worker configuration loaded: "
            "calibration=%s, tag_count=%d"
        ),
        calibration is not None,
        len(
            tags
        ),
    )

    return jsonify({
        "ok": True,
        "calibration": calibration,
        "tags": tags,
    })


def _validate_ocr_run_payload(
    data: Mapping[str, Any],
) -> dict[str, Any]:
    raw_image_path = _required_text(
        data.get(
            "raw_image_path"
        ),
        "raw_image_path",
        MAX_PATH_LENGTH,
    )

    calibrated_image_path = (
        _required_text(
            data.get(
                "calibrated_image_path"
            ),
            "calibrated_image_path",
            MAX_PATH_LENGTH,
        )
    )

    captured_at_text = (
        _required_text(
            data.get(
                "captured_at"
            ),
            "captured_at",
            100,
        )
    )

    parse_text = captured_at_text

    if parse_text.endswith(
        "Z"
    ):
        parse_text = (
            parse_text[:-1]
            + "+00:00"
        )

    try:
        parsed_captured_at = (
            datetime.fromisoformat(
                parse_text
            )
        )

    except ValueError as error:
        raise WorkerRouteValidationError(
            (
                "captured_at must be a "
                "valid ISO 8601 datetime"
            )
        ) from error

    if (
        parsed_captured_at.tzinfo
        is None
    ):
        raise WorkerRouteValidationError(
            (
                "captured_at must include "
                "a timezone offset"
            )
        )

    results = data.get(
        "results"
    )

    if (
        not isinstance(
            results,
            list,
        )
        or not results
    ):
        raise WorkerRouteValidationError(
            (
                "results must be a "
                "non-empty list"
            )
        )

    status = _required_text(
        data.get(
            "status"
        ),
        "status",
        20,
    ).upper()

    if status not in {
        "NORMAL",
        "ALERT",
    }:
        raise WorkerRouteValidationError(
            (
                "status must be "
                "NORMAL or ALERT"
            )
        )

    raw_missing_tags = data.get(
        "missing_tags",
        [],
    )

    if not isinstance(
        raw_missing_tags,
        list,
    ):
        raise WorkerRouteValidationError(
            (
                "missing_tags must "
                "be a list"
            )
        )

    missing_tags = [
        _required_text(
            tag_name,
            f"missing_tags[{index}]",
            150,
        )
        for index, tag_name in enumerate(
            raw_missing_tags
        )
    ]

    for index, item in enumerate(
        results
    ):
        if not isinstance(
            item,
            Mapping,
        ):
            raise WorkerRouteValidationError(
                (
                    f"results[{index}] "
                    "must be an object"
                )
            )

        tag = item.get(
            "tag"
        )

        if not isinstance(
            tag,
            Mapping,
        ):
            raise WorkerRouteValidationError(
                (
                    f"results[{index}].tag "
                    "must be an object"
                )
            )

        _positive_integer(
            tag.get(
                "id"
            ),
            f"results[{index}].tag.id",
        )

        _required_text(
            tag.get(
                "tag_name"
            ),
            (
                f"results[{index}]"
                ".tag.tag_name"
            ),
            150,
        )

    return {
        "raw_image_path": raw_image_path,
        "calibrated_image_path": (
            calibrated_image_path
        ),
        "results": results,
        "status": status,
        "missing_tags": missing_tags,
        "alert_message": _optional_text(
            data.get(
                "alert_message",
                "",
            ),
            "alert_message",
        ),
        "captured_at": (
            parsed_captured_at.isoformat()
        ),
    }


@worker_bp.route(
    "/api/worker/ocr-runs",
    methods=["POST"],
)
@require_api_key
@_handle_route_errors(
    "Worker OCR run save",
    "Cannot save OCR run",
)
def api_worker_create_ocr_run():
    data = _read_json_object()

    validated = (
        _validate_ocr_run_payload(
            data
        )
    )

    run_id = save_worker_ocr_run(
        **validated
    )

    logger.info(
        (
            "Worker OCR run saved: "
            "run_id=%s, status=%s, "
            "value_count=%d"
        ),
        run_id,
        validated[
            "status"
        ],
        len(
            validated[
                "results"
            ]
        ),
    )

    return jsonify({
        "ok": True,
        "message": "OCR run saved",
        "run_id": run_id,
    }), 201


@worker_bp.route(
    "/api/worker/outbound-queue",
    methods=["POST"],
)
@require_api_key
@_handle_route_errors(
    "Outbound queue creation",
    "Cannot create outbound queue",
)
def api_create_outbound_queue():
    data = _read_json_object()

    run_id = _positive_integer(
        data.get(
            "run_id"
        ),
        "run_id",
    )

    sensor_values = data.get(
        "sensor_values"
    )

    if not isinstance(
        sensor_values,
        list,
    ):
        raise WorkerRouteValidationError(
            (
                "sensor_values must "
                "be a list"
            )
        )

    queue_ids = create_queue_items(
        run_id=run_id,
        sensor_values=sensor_values,
    )

    if queue_ids is None:
        queue_ids = []

    logger.info(
        (
            "Outbound queue created: "
            "run_id=%s, item_count=%d"
        ),
        run_id,
        len(
            queue_ids
        ),
    )

    return jsonify({
        "ok": True,
        "message": (
            "Outbound queue created"
        ),
        "queue_ids": queue_ids,
    }), 201


@worker_bp.route(
    "/api/worker/outbound-queue/claim",
    methods=["POST"],
)
@require_api_key
@_handle_route_errors(
    "Outbound queue claim",
    "Cannot claim queue",
)
def api_claim_outbound_queue():
    data = _read_json_object(
        required=False
    )

    limit = _positive_integer(
        data.get(
            "limit",
            100,
        ),
        "limit",
        MAX_CLAIM_LIMIT,
    )

    queue_items = (
        claim_pending_queue(
            limit=limit
        )
    )

    if queue_items is None:
        queue_items = []

    elif not isinstance(
        queue_items,
        list,
    ):
        queue_items = list(
            queue_items
        )

    return jsonify({
        "ok": True,
        "queue_items": queue_items,
    })


@worker_bp.route(
    "/api/worker/outbound-queue/sent",
    methods=["POST"],
)
@require_api_key
@_handle_route_errors(
    "Outbound queue sent update",
    "Cannot update queue",
)
def api_mark_queue_sent():
    data = _read_json_object()

    queue_ids = _parse_queue_ids(
        data.get(
            "queue_ids"
        )
    )

    http_status = (
        _optional_http_status(
            data.get(
                "http_status"
            )
        )
    )

    response_message = _optional_text(
        data.get(
            "response_message",
            "",
        ),
        "response_message",
    )

    updated = mark_queue_sent(
        queue_ids=queue_ids,
        http_status=http_status,
        response_message=response_message,
    )

    logger.info(
        (
            "Outbound queue marked sent: "
            "requested=%d, updated=%s"
        ),
        len(
            queue_ids
        ),
        updated,
    )

    return jsonify({
        "ok": True,
        "updated": updated,
    })


@worker_bp.route(
    "/api/worker/outbound-queue/failed",
    methods=["POST"],
)
@require_api_key
@_handle_route_errors(
    "Outbound queue failed update",
    "Cannot update queue",
)
def api_mark_queue_failed():
    data = _read_json_object()

    queue_ids = _parse_queue_ids(
        data.get(
            "queue_ids"
        )
    )

    error_message = _optional_text(
        data.get(
            "error_message",
            "",
        ),
        "error_message",
    )

    http_status = (
        _optional_http_status(
            data.get(
                "http_status"
            )
        )
    )

    response_message = _optional_text(
        data.get(
            "response_message",
            "",
        ),
        "response_message",
    )

    updated = mark_queue_failed(
        queue_ids=queue_ids,
        error_message=error_message,
        http_status=http_status,
        response_message=response_message,
    )

    logger.info(
        (
            "Outbound queue marked failed: "
            "requested=%d, updated=%s"
        ),
        len(
            queue_ids
        ),
        updated,
    )

    return jsonify({
        "ok": True,
        "updated": updated,
    })


@worker_bp.route(
    "/api/ocr/status",
    methods=["GET"],
)
@require_api_key
@_handle_route_errors(
    "OCR model status load",
    "Cannot load OCR model status",
)
def get_ocr_status():
    model_status = (
        read_model_status_file()
    )

    return jsonify({
        "engine": model_status.get(
            "engine",
            "",
        ),
        "status": model_status.get(
            "status",
            OCRModelStatus.NOT_STARTED.value,
        ),
        "message": model_status.get(
            "message",
            (
                "OCR model preparation "
                "has not started"
            ),
        ),
        "error": model_status.get(
            "error",
            "",
        ),
        "updated_at": model_status.get(
            "updated_at",
            "",
        ),
    })