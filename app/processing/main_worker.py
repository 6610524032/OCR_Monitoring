import time
from datetime import datetime

import cv2

from app.processing.calibration import create_calibrated_image
from app.processing.capture import capture_image
from app.processing.rtsp_capture import capture_rtsp_image
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


def save_ocr_results(
    raw_image_path,
    calibrated_image_path,
    results,
    status,
    missing_tags,
    alert_message
):
    payload = {
        "raw_image_path": str(raw_image_path),
        "calibrated_image_path": str(
            calibrated_image_path
        ),
        "results": results,
        "status": status,
        "missing_tags": missing_tags,
        "alert_message": alert_message
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


def process_ocr_for_tags(
    raw_image_path,
    calibrated_image_path,
    tags
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

    return save_ocr_results(
        raw_image_path=raw_image_path,
        calibrated_image_path=calibrated_image_path,
        results=results,
        status=status,
        missing_tags=missing_tags,
        alert_message=alert_message
    )


def process_new_image(raw_image_path):
    print("New image found:", raw_image_path)

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
            tags=tags
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

    last_capture_key = None

    while True:
        should_capture, capture_key = should_capture_rtsp_now(
            last_capture_key
        )

        if should_capture:
            capture_rtsp_image()
            last_capture_key = capture_key

        raw_image_path = capture_image()

        if raw_image_path:
            process_new_image(raw_image_path)
        else:
            print("No new image")

        time.sleep(PROCESS_CHECK_INTERVAL)


if __name__ == "__main__":
    main()