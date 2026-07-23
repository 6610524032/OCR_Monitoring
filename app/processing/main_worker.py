import time
from datetime import datetime
from threading import Thread

import cv2

from app.processing.calibration import (
    create_calibrated_image
)
from app.processing.capture import capture_image
from app.processing.rtsp_capture import (
    capture_rtsp_image
)
from app.processing.sender_worker import (
    sender_loop
)
from app.processing.trocr_engine import (
    crop_by_roi,
    read_crop_with_trocr
)
from app.server.api_client import (
    ApiClientError,
    api_get,
    api_post
)
from app.server.config import (
    PROCESS_CHECK_INTERVAL,
    RTSP_CAPTURE_ENABLED,
    RTSP_CAPTURE_MINUTES
)


def fetch_worker_config():
    result = api_get("/api/worker/config")

    if not result.get("ok"):
        raise ApiClientError(
            result.get(
                "message",
                "Cannot load worker configuration"
            )
        )

    return {
        "calibration": result.get("calibration"),
        "tags": result.get("tags", [])
    }


def read_all_tags_from_image(calibrated_image_path, tags):
    image = cv2.imread(str(calibrated_image_path))

    if image is None:
        print("Cannot read calibrated image")
        return [], []

    results = []
    missing_tags = []

    print(f"Reading {len(tags)} ROI tag(s)...")

    for tag in tags:
        tag_name = tag["tag_name"]
        crop = crop_by_roi(image, tag)
        ocr_result = read_crop_with_trocr(crop)

        value = ""
        raw_text = ""

        if ocr_result.get("ok"):
            value = str(ocr_result.get("value", "")).strip()
            raw_text = str(ocr_result.get("raw_text", "")).strip()
        else:
            raw_text = str(ocr_result.get("message", "")).strip()

        if value == "":
            missing_tags.append(tag_name)

        results.append({
            "tag": tag,
            "value": value,
            "raw_text": raw_text
        })

        print(f"{tag_name}: value={value!r} raw={raw_text!r}")

    return results, missing_tags


def get_run_status(missing_tags):
    if missing_tags:
        return "ALERT", "Missing: " + ", ".join(missing_tags)

    return "NORMAL", ""

def build_vulcan_sensor_values(
    results,
    capture_timestamp
):
    sensor_values = []

    for result in results:
        tag = result["tag"]

        api_key = str(
            tag.get("sensor_api_key", "")
        ).strip()

        if not api_key:
            continue

        value = str(
            result.get("value", "")
        ).strip()

        try:
            numeric_value = float(value)
        except ValueError:
            continue

        sensor_values.append({
            "tag_id": tag["id"],
            "tag_name": tag["tag_name"],
            "sensor_api_key": api_key,
            "capture_timestamp": capture_timestamp,
            "value": numeric_value
        })

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
    payload = {
        "raw_image_path": str(raw_image_path),
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
        raise ApiClientError(
            response.get(
                "message",
                "Cannot save OCR run"
            )
        )

    run_id = response.get("run_id")

    print(
        f"OCR saved through API. "
        f"run_id={run_id}, status={status}"
    )

    if alert_message:
        print(alert_message)

    return run_id


def create_outbound_queue(
    run_id,
    sensor_values
):
    payload = {
        "run_id": run_id,
        "sensor_values": sensor_values
    }

    response = api_post(
        "/api/worker/outbound-queue",
        payload=payload
    )

    if not response.get("ok"):
        raise ApiClientError(
            response.get(
                "message",
                "Cannot create outbound queue"
            )
        )

    queue_ids = response.get(
        "queue_ids",
        []
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
    if not tags:
        print(
            "No active user tags. "
            "Please set ROI tags in Settings first."
        )
        return None

    results, missing_tags = read_all_tags_from_image(
        calibrated_image_path=calibrated_image_path,
        tags=tags
    )

    if not results:
        return None

    status, alert_message = get_run_status(
        missing_tags
    )

    run_id = save_ocr_results(
        raw_image_path=raw_image_path,
        calibrated_image_path=calibrated_image_path,
        results=results,
        status=status,
        missing_tags=missing_tags,
        alert_message=alert_message,
        captured_at=captured_at,
        capture_timestamp=capture_timestamp
    )

    sensor_values = build_vulcan_sensor_values(
        results=results,
        capture_timestamp=capture_timestamp
    )

    print(
        "Prepared",
        len(sensor_values),
        "sensor value(s) for Vulcan"
    )

    if not sensor_values:
        print(
            "[VULCAN] No valid sensor values to send"
        )
        return run_id

    queue_ids = create_outbound_queue(
        run_id=run_id,
        sensor_values=sensor_values
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
    print("New image found:", raw_image_path)
    print("Captured at:", captured_at)
    print("Capture timestamp:", capture_timestamp)

    try:
        worker_config = fetch_worker_config()

    except ApiClientError as error:
        print(
            "Cannot load worker configuration "
            f"from API: {error}"
        )
        return None

    calibration = worker_config["calibration"]
    tags = worker_config["tags"]

    if calibration is None:
        print(
            "No active calibration. "
            "Please set calibration first."
        )
        return None

    if not tags:
        print(
            "No active user tags. "
            "Please set ROI tags in Settings first."
        )
        return None

    calibrated_path = create_calibrated_image(
        raw_image_path=raw_image_path,
        calibration=calibration
    )

    if calibrated_path is None:
        return None

    print("Calibrated image:", calibrated_path)

    try:
        run_id = process_ocr_for_tags(
            raw_image_path=raw_image_path,
            calibrated_image_path=calibrated_path,
            tags=tags,
            captured_at=captured_at,
            capture_timestamp=capture_timestamp
        )

    except ApiClientError as error:
        print(
            "Cannot save OCR result through API: "
            f"{error}"
        )
        return None

    print("Image process completed")

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


def main():
    print("OCR Worker Started")
    print("All data access uses API")
    print("RTSP capture uses real clock time")
    print("Waiting for images in data/incoming/")
    print("Press Ctrl + C to stop")

    sender_thread = Thread(
        target=sender_loop,
        name="VulcanSenderWorker",
        daemon=True
    )
    sender_thread.start()

    print("Vulcan Sender Worker Started")

    last_capture_key = None

    while True:
        should_capture, capture_key = (
            should_capture_rtsp_now(
                last_capture_key
            )
        )

        print(
            "[RTSP]",
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "should_capture =",
            should_capture
        )

        if should_capture:
            print(
                "[RTSP] Scheduled capture..."
            )

            capture_result = (
                capture_rtsp_image()
            )

            if (
                capture_result
                and capture_result.get("ok")
            ):
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

        else:
            print("No new image")

        time.sleep(
            PROCESS_CHECK_INTERVAL
        )


if __name__ == "__main__":
    main()