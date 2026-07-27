import time
from datetime import datetime
from threading import Thread

import cv2

from src.logger import create_logger
from src.processing.calibration import (
    create_calibrated_image
)
from src.processing.capture import capture_image
from src.processing.rtsp_capture import (
    capture_rtsp_image
)
from src.processing.sender_worker import (
    sender_loop
)
from src.processing.ocr.service import (
    crop_by_roi,
    read_crop,
)
from src.processing.ocr.factory import (
    get_ocr_provider,
)
from src.processing.ocr.model_status import (
    OCRModelStatus,
    get_model_state,
    set_model_status,
)
from src.server.api_client import (
    ApiClientError,
    api_get,
    api_post
)
from src.server.config import (
    INCOMING_DIR,
    PROCESS_CHECK_INTERVAL,
    RTSP_CAPTURE_ENABLED,
    RTSP_CAPTURE_MINUTES
)


logger = create_logger("processing.main_worker")


def fetch_worker_config():
    logger.info(
        "Fetching worker configuration from API"
    )

    result = api_get(
        "/api/worker/config"
    )

    if not result.get("ok"):
        error_message = result.get(
            "message",
            "Cannot load worker configuration"
        )

        logger.error(
            "Cannot load worker configuration: %s",
            error_message
        )

        raise ApiClientError(
            error_message
        )

    calibration = result.get(
        "calibration"
    )
    tags = result.get(
        "tags",
        []
    )

    logger.info(
        (
            "Worker configuration loaded successfully: "
            "calibration_available=%s, tag_count=%d"
        ),
        calibration is not None,
        len(tags)
    )

    return {
        "calibration": calibration,
        "tags": tags
    }


def read_all_tags_from_image(
    calibrated_image_path,
    tags
):
    image = cv2.imread(
        str(calibrated_image_path)
    )

    if image is None:
        logger.error(
            "Cannot read calibrated image: %s",
            calibrated_image_path
        )
        return [], []

    results = []
    missing_tags = []

    logger.info(
        "Starting OCR for %d ROI tag(s): image=%s",
        len(tags),
        calibrated_image_path
    )

    print(
        f"Reading {len(tags)} ROI tag(s)..."
    )

    for tag in tags:
        tag_name = str(
            tag.get(
                "tag_name",
                "Unknown tag"
            )
        )

        try:
            crop = crop_by_roi(
                image,
                tag
            )

            ocr_result = read_crop(
                crop
            )

        except Exception:
            logger.exception(
                "Unexpected OCR error for tag: %s",
                tag_name
            )

            results.append({
                "tag": tag,
                "value": "",
                "raw_text": (
                    "Unexpected OCR processing error"
                )
            })

            missing_tags.append(
                tag_name
            )
            continue

        value = ""
        raw_text = ""

        if ocr_result.get("ok"):
            value = str(
                ocr_result.get(
                    "value",
                    ""
                )
            ).strip()

            raw_text = str(
                ocr_result.get(
                    "raw_text",
                    ""
                )
            ).strip()

        else:
            raw_text = str(
                ocr_result.get(
                    "message",
                    ""
                )
            ).strip()

            logger.warning(
                (
                    "OCR could not read tag: "
                    "tag_name=%s, message=%s"
                ),
                tag_name,
                raw_text
            )

        if value == "":
            missing_tags.append(
                tag_name
            )

        results.append({
            "tag": tag,
            "value": value,
            "raw_text": raw_text
        })

        print(
            f"{tag_name}: "
            f"value={value!r} "
            f"raw={raw_text!r}"
        )

    if missing_tags:
        logger.warning(
            "OCR completed with missing tags: %s",
            ", ".join(missing_tags)
        )
    else:
        logger.info(
            "OCR completed successfully for all %d tag(s)",
            len(tags)
        )

    return results, missing_tags


def get_run_status(
    missing_tags
):
    if missing_tags:
        alert_message = (
            "Missing: "
            + ", ".join(missing_tags)
        )

        logger.warning(
            "OCR run status is ALERT: %s",
            alert_message
        )

        return (
            "ALERT",
            alert_message
        )

    logger.info(
        "OCR run status is NORMAL"
    )

    return "NORMAL", ""


def build_vulcan_sensor_values(
    results,
    capture_timestamp
):
    sensor_values = []

    logger.info(
        (
            "Preparing Vulcan sensor values: "
            "result_count=%d, capture_timestamp=%s"
        ),
        len(results),
        capture_timestamp
    )

    for result in results:
        tag = result["tag"]

        tag_name = str(
            tag.get(
                "tag_name",
                "Unknown tag"
            )
        )

        api_key = str(
            tag.get(
                "sensor_api_key",
                ""
            )
        ).strip()

        if not api_key:
            logger.warning(
                (
                    "Skipping Vulcan value because "
                    "sensor API key is missing: tag=%s"
                ),
                tag_name
            )
            continue

        value = str(
            result.get(
                "value",
                ""
            )
        ).strip()

        try:
            numeric_value = float(
                value
            )

        except (TypeError, ValueError):
            logger.warning(
                (
                    "Skipping invalid Vulcan value: "
                    "tag=%s, value=%r"
                ),
                tag_name,
                value
            )
            continue

        sensor_values.append({
            "tag_id": tag["id"],
            "tag_name": tag_name,
            "sensor_api_key": api_key,
            "capture_timestamp": (
                capture_timestamp
            ),
            "value": numeric_value
        })

    logger.info(
        "Prepared %d valid sensor value(s) for Vulcan",
        len(sensor_values)
    )

    return sensor_values

def save_ocr_results(
    raw_image_path,
    calibrated_image_path,
    results,
    status,
    missing_tags,
    alert_message,
    captured_at,
    capture_timestamp
):
    logger.info(
        (
            "Saving OCR result through API: "
            "status=%s, result_count=%d, "
            "missing_tag_count=%d"
        ),
        status,
        len(results),
        len(missing_tags)
    )

    payload = {
        "raw_image_path": str(
            raw_image_path
        ),
        "calibrated_image_path": str(
            calibrated_image_path
        ),
        "results": results,
        "status": status,
        "missing_tags": missing_tags,
        "alert_message": alert_message,
        "captured_at": captured_at,
    }

    response = api_post(
        "/api/worker/ocr-runs",
        payload=payload
    )

    if not response.get("ok"):
        error_message = response.get(
            "message",
            "Cannot save OCR run"
        )

        logger.error(
            "Cannot save OCR run through API: %s",
            error_message
        )

        raise ApiClientError(
            error_message
        )

    run_id = response.get(
        "run_id"
    )

    logger.info(
        (
            "OCR result saved successfully: "
            "run_id=%s, status=%s"
        ),
        run_id,
        status
    )

    print(
        f"OCR saved through API. "
        f"run_id={run_id}, status={status}"
    )

    if alert_message:
        logger.warning(
            (
                "OCR result contains an alert: "
                "run_id=%s, message=%s"
            ),
            run_id,
            alert_message
        )

        print(
            alert_message
        )

    return run_id


def create_outbound_queue(
    run_id,
    sensor_values
):
    logger.info(
        (
            "Creating outbound queue: "
            "run_id=%s, sensor_value_count=%d"
        ),
        run_id,
        len(sensor_values)
    )

    payload = {
        "run_id": run_id,
        "sensor_values": sensor_values
    }

    response = api_post(
        "/api/worker/outbound-queue",
        payload=payload
    )

    if not response.get("ok"):
        error_message = response.get(
            "message",
            "Cannot create outbound queue"
        )

        logger.error(
            (
                "Cannot create outbound queue: "
                "run_id=%s, error=%s"
            ),
            run_id,
            error_message
        )

        raise ApiClientError(
            error_message
        )

    queue_ids = response.get(
        "queue_ids",
        []
    )

    logger.info(
        (
            "Outbound queue created successfully: "
            "run_id=%s, queue_item_count=%d"
        ),
        run_id,
        len(queue_ids)
    )

    print(
        f"Created {len(queue_ids)} "
        "queue item(s)"
    )

    return queue_ids


def process_ocr_for_tags(
    raw_image_path,
    calibrated_image_path,
    tags,
    captured_at,
    capture_timestamp
):
    model_state = get_model_state()

    if (
        model_state.status
        != OCRModelStatus.READY
    ):
        logger.warning(
            (
                "OCR processing skipped because "
                "the model is not ready: "
                "status=%s, message=%s"
            ),
            model_state.status.value,
            model_state.message
        )

        print(
            "[OCR] Model is not ready:",
            model_state.status.value,
            "-",
            model_state.message,
        )

        return None

    if not tags:
        logger.warning(
            (
                "OCR processing skipped because "
                "no active ROI tags are configured"
            )
        )

        print(
            "No active user tags. "
            "Please set ROI tags in Settings first."
        )

        return None

    logger.info(
        (
            "Starting OCR processing: "
            "tag_count=%d, image=%s"
        ),
        len(tags),
        calibrated_image_path
    )

    results, missing_tags = (
        read_all_tags_from_image(
            calibrated_image_path=(
                calibrated_image_path
            ),
            tags=tags
        )
    )

    if not results:
        logger.error(
            (
                "OCR processing produced no results: "
                "image=%s"
            ),
            calibrated_image_path
        )

        return None

    logger.info(
        (
            "OCR processing completed: "
            "result_count=%d, missing_tag_count=%d"
        ),
        len(results),
        len(missing_tags)
    )

    status, alert_message = (
        get_run_status(
            missing_tags
        )
    )

    run_id = save_ocr_results(
        raw_image_path=raw_image_path,
        calibrated_image_path=(
            calibrated_image_path
        ),
        results=results,
        status=status,
        missing_tags=missing_tags,
        alert_message=alert_message,
        captured_at=captured_at,
        capture_timestamp=capture_timestamp
    )

    sensor_values = (
        build_vulcan_sensor_values(
            results=results,
            capture_timestamp=(
                capture_timestamp
            )
        )
    )

    print(
        "Prepared",
        len(sensor_values),
        "sensor value(s) for Vulcan"
    )

    if not sensor_values:
        logger.warning(
            (
                "No valid sensor values were "
                "prepared for Vulcan: run_id=%s"
            ),
            run_id
        )

        print(
            "[VULCAN] "
            "No valid sensor values to send"
        )

        return run_id

    queue_ids = create_outbound_queue(
        run_id=run_id,
        sensor_values=sensor_values
    )

    logger.info(
        (
            "OCR run prepared for Vulcan delivery: "
            "run_id=%s, queue_item_count=%d"
        ),
        run_id,
        len(queue_ids)
    )

    print(
        "[QUEUE]",
        queue_ids
    )

    return run_id


def process_new_image(
    raw_image_path,
    captured_at,
    capture_timestamp
):
    logger.info(
        (
            "New image processing started: "
            "image=%s, captured_at=%s, "
            "capture_timestamp=%s"
        ),
        raw_image_path,
        captured_at,
        capture_timestamp
    )

    print(
        "New image found:",
        raw_image_path
    )
    print(
        "Captured at:",
        captured_at
    )
    print(
        "Capture timestamp:",
        capture_timestamp
    )

    try:
        worker_config = (
            fetch_worker_config()
        )

    except ApiClientError as error:
        logger.error(
            (
                "Cannot process image because "
                "worker configuration could not "
                "be loaded: image=%s, error=%s"
            ),
            raw_image_path,
            error
        )

        print(
            "Cannot load worker configuration "
            f"from API: {error}"
        )

        return None

    calibration = worker_config[
        "calibration"
    ]
    tags = worker_config[
        "tags"
    ]

    if calibration is None:
        logger.warning(
            (
                "Image processing skipped because "
                "no active calibration is configured: "
                "image=%s"
            ),
            raw_image_path
        )

        print(
            "No active calibration. "
            "Please set calibration first."
        )

        return None

    if not tags:
        logger.warning(
            (
                "Image processing skipped because "
                "no active ROI tags are configured: "
                "image=%s"
            ),
            raw_image_path
        )

        print(
            "No active user tags. "
            "Please set ROI tags in Settings first."
        )

        return None

    try:
        calibrated_path = (
            create_calibrated_image(
                raw_image_path=(
                    raw_image_path
                ),
                calibration=calibration
            )
        )

    except Exception:
        logger.exception(
            (
                "Unexpected calibration error: "
                "image=%s"
            ),
            raw_image_path
        )

        return None

    if calibrated_path is None:
        logger.error(
            (
                "Calibration did not produce "
                "an output image: image=%s"
            ),
            raw_image_path
        )

        return None

    logger.info(
        (
            "Image calibration completed: "
            "raw_image=%s, calibrated_image=%s"
        ),
        raw_image_path,
        calibrated_path
    )

    print(
        "Calibrated image:",
        calibrated_path
    )

    try:
        run_id = process_ocr_for_tags(
            raw_image_path=raw_image_path,
            calibrated_image_path=(
                calibrated_path
            ),
            tags=tags,
            captured_at=captured_at,
            capture_timestamp=(
                capture_timestamp
            )
        )

    except ApiClientError as error:
        logger.error(
            (
                "Cannot complete OCR processing "
                "through API: image=%s, error=%s"
            ),
            raw_image_path,
            error
        )

        print(
            "Cannot save OCR result through API: "
            f"{error}"
        )

        return None

    except Exception:
        logger.exception(
            (
                "Unexpected image processing error: "
                "image=%s"
            ),
            raw_image_path
        )

        return None

    if run_id is None:
        logger.warning(
            (
                "Image processing ended without "
                "creating an OCR run: image=%s"
            ),
            raw_image_path
        )

        return None

    logger.info(
        (
            "Image processing completed successfully: "
            "image=%s, run_id=%s"
        ),
        raw_image_path,
        run_id
    )

    print(
        "Image process completed"
    )

    return run_id


def should_capture_rtsp_now(last_capture_key):
    if not RTSP_CAPTURE_ENABLED:
        return False, last_capture_key

    now = datetime.now()

    if now.minute not in RTSP_CAPTURE_MINUTES:
        return False, last_capture_key

    capture_key = now.strftime("%Y-%m-%d_%H-%M")

    if capture_key == last_capture_key:
        return False, last_capture_key

    return True, capture_key


def prepare_ocr_model():
    logger.info(
        "Preparing OCR model in background"
    )

    try:
        provider = get_ocr_provider()
        provider.load_model()

        logger.info(
            "OCR model loaded successfully"
        )

        print(
            "[OCR MODEL] Model is ready"
        )

    except Exception as error:
        set_model_status(
            OCRModelStatus.ERROR,
            message="Cannot prepare OCR model",
            error=str(error),
        )

        logger.exception(
            "Cannot prepare OCR model"
        )

        print(
            "[OCR MODEL ERROR]",
            type(error).__name__,
            str(error),
        )


def main():
    logger.info(
        "OCR Worker started"
    )

    print("OCR Worker Started")
    print("All data access uses API")
    print("RTSP capture uses real clock time")
    print(f"Waiting for images in {INCOMING_DIR}")
    print("Press Ctrl + C to stop")

    ocr_model_thread = Thread(
        target=prepare_ocr_model,
        name="OCRModelLoader",
        daemon=True,
    )
    ocr_model_thread.start()

    logger.info(
        "OCR Model Loader thread started"
    )

    print("OCR Model Loader Started")

    sender_thread = Thread(
        target=sender_loop,
        name="VulcanSenderWorker",
        daemon=True
    )
    sender_thread.start()

    logger.info(
        "Vulcan Sender Worker thread started"
    )

    print("Vulcan Sender Worker Started")

    last_capture_key = None

    while True:
        try:
            should_capture, capture_key = (
                should_capture_rtsp_now(
                    last_capture_key
                )
            )

            if should_capture:
                print(
                    "[RTSP] Scheduled capture..."
                )

                logger.info(
                    "Starting scheduled RTSP capture"
                )

                capture_result = (
                    capture_rtsp_image()
                )

                if (
                    capture_result
                    and capture_result.get("ok")
                ):
                    logger.info(
                        "Scheduled RTSP capture completed successfully"
                    )

                    print(
                        "[RTSP] Capture successful"
                    )

                    process_new_image(
                        raw_image_path=(
                            capture_result[
                                "image_path"
                            ]
                        ),
                        captured_at=(
                            capture_result[
                                "captured_at"
                            ]
                        ),
                        capture_timestamp=(
                            capture_result[
                                "capture_timestamp"
                            ]
                        )
                    )

                else:
                    logger.error(
                        "Scheduled RTSP capture failed: %s",
                        capture_result
                    )

                    print(
                        "[RTSP] Capture failed:",
                        capture_result
                    )

                last_capture_key = (
                    capture_key
                )

            capture_result = capture_image()

            if capture_result:
                process_new_image(
                    raw_image_path=(
                        capture_result[
                            "image_path"
                        ]
                    ),
                    captured_at=(
                        capture_result[
                            "captured_at"
                        ]
                    ),
                    capture_timestamp=(
                        capture_result[
                            "capture_timestamp"
                        ]
                    )
                )

            time.sleep(
                PROCESS_CHECK_INTERVAL
            )

        except Exception:
            logger.exception(
                "Unexpected error in OCR worker loop"
            )

            time.sleep(
                PROCESS_CHECK_INTERVAL
            )


if __name__ == "__main__":
    main()