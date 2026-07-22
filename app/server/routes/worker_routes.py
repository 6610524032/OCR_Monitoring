from datetime import datetime
from flask import Blueprint, jsonify, request

from app.processing.trocr_engine import read_manual_roi

from app.server.auth import require_api_key
from app.server.repositories.configuration_repository import (
    reset_configuration_data
)

from app.server.repositories.calibration_repository import (
    get_active_calibration
)
from app.server.repositories.ocr_repository import (
    save_worker_ocr_run
)
from app.server.repositories.tag_repository import (
    get_active_user_tags
)
from app.server.repositories.queue_repository import (
    claim_pending_queue,
    create_queue_items,
    mark_queue_failed,
    mark_queue_sent
)
worker_bp = Blueprint(
    "worker",
    __name__
)


@worker_bp.route("/api/read_manual_roi", methods=["POST"])
@require_api_key
def api_read_manual_roi():
    data = request.json or {}

    result = read_manual_roi(
        image_name=data.get("image"),
        x1=data.get("x1"),
        y1=data.get("y1"),
        x2=data.get("x2"),
        y2=data.get("y2")
    )

    print("[MANUAL OCR RESULT]", result)

    return jsonify(result)


@worker_bp.route("/api/reset_configuration", methods=["POST"])
@require_api_key
def api_reset_configuration():
    result = reset_configuration_data()

    return jsonify(result)


@worker_bp.route("/api/worker/config")
@require_api_key
def api_worker_config():
    calibration = get_active_calibration()
    tags = get_active_user_tags()

    return jsonify({
        "ok": True,
        "calibration": calibration,
        "tags": tags
    })


@worker_bp.route("/api/worker/ocr-runs", methods=["POST"])
@require_api_key
def api_worker_create_ocr_run():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "ok": False,
            "message": "JSON request body is required"
        }), 400

    raw_image_path = data.get("raw_image_path")
    calibrated_image_path = data.get(
        "calibrated_image_path"
    )
    results = data.get("results")
    status = str(data.get("status", "")).strip().upper()
    missing_tags = data.get("missing_tags", [])
    alert_message = str(
        data.get("alert_message", "")
    ).strip()

    captured_at = str(
        data.get("captured_at", "")
    ).strip()

    if not raw_image_path:
        return jsonify({
            "ok": False,
            "message": "raw_image_path is required"
        }), 400

    if not calibrated_image_path:
        return jsonify({
            "ok": False,
            "message": "calibrated_image_path is required"
        }), 400

    if not captured_at:
        return jsonify({
            "ok": False,
            "message": "captured_at is required"
        }), 400

    try:
        parsed_captured_at = datetime.fromisoformat(
            captured_at
        )

    except ValueError:
        return jsonify({
            "ok": False,
            "message": (
                "captured_at must be a valid "
                "ISO 8601 datetime"
            )
        }), 400
    if parsed_captured_at.tzinfo is None:
        return jsonify({
            "ok": False,
            "message": (
                "captured_at must include "
                "a timezone offset"
            )
        }), 400

    if not isinstance(results, list) or not results:
        return jsonify({
            "ok": False,
            "message": "results must be a non-empty list"
        }), 400

    if status not in {"NORMAL", "ALERT"}:
        return jsonify({
            "ok": False,
            "message": "status must be NORMAL or ALERT"
        }), 400

    if not isinstance(missing_tags, list):
        return jsonify({
            "ok": False,
            "message": "missing_tags must be a list"
        }), 400

    for index, item in enumerate(results):
        if not isinstance(item, dict):
            return jsonify({
                "ok": False,
                "message": (
                    f"results[{index}] must be an object"
                )
            }), 400

        tag = item.get("tag")

        if not isinstance(tag, dict):
            return jsonify({
                "ok": False,
                "message": (
                    f"results[{index}].tag is required"
                )
            }), 400

        if not tag.get("id") or not tag.get("tag_name"):
            return jsonify({
                "ok": False,
                "message": (
                    f"results[{index}].tag must contain "
                    "id and tag_name"
                )
            }), 400

    try:
        run_id = save_worker_ocr_run(
            raw_image_path=raw_image_path,
            calibrated_image_path=calibrated_image_path,
            results=results,
            status=status,
            missing_tags=[
                str(tag_name)
                for tag_name in missing_tags
            ],
            alert_message=alert_message,
            captured_at=captured_at
        )

    except Exception as error:
        print(
            "[WORKER OCR SAVE ERROR]",
            type(error).__name__,
            str(error)
        )

        return jsonify({
            "ok": False,
            "message": "Cannot save OCR run"
        }), 500

    return jsonify({
        "ok": True,
        "message": "OCR run saved",
        "run_id": run_id
    }), 201


@worker_bp.route(
    "/api/worker/outbound-queue",
    methods=["POST"]
)
@require_api_key
def api_create_outbound_queue():
    data = request.get_json(
        silent=True
    )

    if not isinstance(data, dict):
        return jsonify({
            "ok": False,
            "message": (
                "JSON request body is required"
            )
        }), 400

    run_id = data.get("run_id")
    sensor_values = data.get(
        "sensor_values"
    )

    if not run_id:
        return jsonify({
            "ok": False,
            "message": (
                "run_id is required"
            )
        }), 400

    if not isinstance(
        sensor_values,
        list
    ):
        return jsonify({
            "ok": False,
            "message": (
                "sensor_values must be a list"
            )
        }), 400

    try:
        queue_ids = create_queue_items(
            run_id=run_id,
            sensor_values=sensor_values
        )

    except Exception as error:
        print(
            "[QUEUE ERROR]",
            type(error).__name__,
            str(error)
        )

        return jsonify({
            "ok": False,
            "message": (
                "Cannot create outbound queue"
            )
        }), 500

    return jsonify({
        "ok": True,
        "message": (
            "Outbound queue created"
        ),
        "queue_ids": queue_ids
    }), 201


@worker_bp.route(
    "/api/worker/outbound-queue/claim",
    methods=["POST"]
)
@require_api_key
def api_claim_outbound_queue():
    data = request.get_json(
        silent=True
    ) or {}

    limit = data.get(
        "limit",
        100
    )

    try:
        queue_items = claim_pending_queue(
            limit=int(limit)
        )

    except Exception as error:
        print(
            "[QUEUE CLAIM ERROR]",
            type(error).__name__,
            str(error)
        )

        return jsonify({
            "ok": False,
            "message": "Cannot claim queue"
        }), 500

    return jsonify({
        "ok": True,
        "queue_items": queue_items
    })


@worker_bp.route(
    "/api/worker/outbound-queue/sent",
    methods=["POST"]
)
@require_api_key
def api_mark_queue_sent():
    data = request.get_json(
        silent=True
    ) or {}

    queue_ids = data.get(
        "queue_ids",
        []
    )

    if not isinstance(queue_ids, list):
        return jsonify({
            "ok": False,
            "message": (
                "queue_ids must be a list"
            )
        }), 400

    http_status = data.get(
        "http_status"
    )

    response_message = data.get(
        "response_message",
        ""
    )

    try:
        updated = mark_queue_sent(
            queue_ids=queue_ids,
            http_status=http_status,
            response_message=response_message
        )

    except Exception as error:
        print(
            "[QUEUE SENT ERROR]",
            type(error).__name__,
            str(error)
        )

        return jsonify({
            "ok": False,
            "message": "Cannot update queue"
        }), 500

    return jsonify({
        "ok": True,
        "updated": updated
    })
    

@worker_bp.route(
    "/api/worker/outbound-queue/failed",
    methods=["POST"]
)
@require_api_key
def api_mark_queue_failed():
    data = request.get_json(
        silent=True
    ) or {}

    queue_ids = data.get(
        "queue_ids",
        []
    )

    if not isinstance(queue_ids, list):
        return jsonify({
            "ok": False,
            "message": (
                "queue_ids must be a list"
            )
        }), 400

    error_message = data.get(
        "error_message",
        ""
    )

    http_status = data.get(
        "http_status"
    )

    response_message = data.get(
        "response_message",
        ""
    )

    try:
        updated = mark_queue_failed(
            queue_ids=queue_ids,
            error_message=error_message,
            http_status=http_status,
            response_message=response_message
        )

    except Exception as error:
        print(
            "[QUEUE FAILED ERROR]",
            type(error).__name__,
            str(error)
        )

        return jsonify({
            "ok": False,
            "message": "Cannot update queue"
        }), 500

    return jsonify({
        "ok": True,
        "updated": updated
    })