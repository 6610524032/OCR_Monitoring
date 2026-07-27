import time
from typing import Any
from urllib.parse import urlparse

import requests

from src.logger import create_logger


logger = create_logger(
    "processing.vulcan_client"
)


VULCAN_SENSOR_DATA_URL = (
    "https://vulcan.mtec.or.th/"
    "api/points/sensor-data"
)

DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_READ_TIMEOUT_SECONDS = 20


def _get_safe_endpoint_name() -> str:
    """
    Return only the destination hostname for logging.

    This avoids logging query strings, credentials,
    API keys, or request payloads.
    """
    try:
        parsed_url = urlparse(
            VULCAN_SENSOR_DATA_URL
        )

        return (
            parsed_url.hostname
            or "unknown-host"
        )

    except Exception:
        return "unknown-host"


def build_vulcan_payload(
    sensor_values: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """
    Convert OCR sensor values into the payload required
    by the Vulcan sensor-data API.

    Each item in sensor_values must contain:
    - sensor_api_key
    - capture_timestamp
    - value
    """
    sensors = []

    for index, item in enumerate(
        sensor_values
    ):
        api_key = str(
            item.get(
                "sensor_api_key",
                ""
            )
        ).strip()

        capture_timestamp = item.get(
            "capture_timestamp"
        )

        value = item.get(
            "value"
        )

        if not api_key:
            logger.error(
                "Missing API key for sensor %d",
                index + 1,
            )

            raise ValueError(
                f"Sensor number {index + 1} "
                "does not have an API key"
            )

        if capture_timestamp is None:
            logger.error(
                (
                    "Missing capture timestamp "
                    "for sensor %d"
                ),
                index + 1,
            )

            raise ValueError(
                f"Sensor number {index + 1} "
                "does not have a capture timestamp"
            )

        if value is None:
            logger.error(
                "Missing value for sensor %d",
                index + 1,
            )

            raise ValueError(
                f"Sensor number {index + 1} "
                "does not have a value"
            )

        try:
            timestamp_value = int(
                capture_timestamp
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            logger.error(
                (
                    "Invalid capture timestamp "
                    "for sensor %d"
                ),
                index + 1,
            )

            raise ValueError(
                "Invalid capture timestamp for "
                f"sensor number {index + 1}"
            ) from error

        try:
            numeric_value = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ) as error:
            logger.error(
                (
                    "Invalid sensor value "
                    "for sensor %d"
                ),
                index + 1,
            )

            raise ValueError(
                "Invalid sensor value for "
                f"sensor number {index + 1}"
            ) from error

        sensors.append({
            "apikey": api_key,
            "data": [
                {
                    "timestamp": timestamp_value,
                    "value": numeric_value,
                }
            ],
        })

    if not sensors:
        logger.error(
            "No sensor values were provided"
        )

        raise ValueError(
            "No sensor values were provided"
        )

    logger.info(
        "Built Vulcan payload for %d sensor(s)",
        len(sensors),
    )

    return {
        "sensors": sensors,
    }


def _create_failed_result(
    message: str,
    payload: dict[str, Any] | None,
    status_code: int | None = None,
    response: Any = None,
) -> dict[str, Any]:
    """
    Create a standard failed result.
    """
    return {
        "ok": False,
        "message": message,
        "status_code": status_code,
        "payload": payload,
        "response": response,
    }


def send_sensor_values_to_vulcan(
    sensor_values: list[dict[str, Any]],
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """
    Build and send sensor values to Vulcan.

    The request uses separate connect and read timeouts
    so the log can identify which stage failed.

    The timeout_seconds argument is retained for
    compatibility with existing callers. When provided,
    it is used as the read timeout.
    """
    payload = None
    endpoint_name = (
        _get_safe_endpoint_name()
    )

    connect_timeout = (
        DEFAULT_CONNECT_TIMEOUT_SECONDS
    )

    read_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else DEFAULT_READ_TIMEOUT_SECONDS
    )

    try:
        read_timeout = int(
            read_timeout
        )

        if read_timeout <= 0:
            raise ValueError(
                "Timeout must be greater than zero"
            )

    except (
        TypeError,
        ValueError,
    ) as error:
        logger.error(
            "Invalid Vulcan timeout setting: %s",
            error,
        )

        return _create_failed_result(
            message=(
                "Invalid Vulcan timeout setting"
            ),
            payload=None,
        )

    try:
        payload = build_vulcan_payload(
            sensor_values
        )

    except ValueError as error:
        logger.error(
            "Cannot build Vulcan payload: %s",
            error,
        )

        return _create_failed_result(
            message=str(
                error
            ),
            payload=None,
        )

    logger.info(
        (
            "Starting Vulcan API request: "
            "destination=%s, "
            "sensor_count=%d, "
            "connect_timeout=%ds, "
            "read_timeout=%ds"
        ),
        endpoint_name,
        len(sensor_values),
        connect_timeout,
        read_timeout,
    )

    request_started_at = (
        time.monotonic()
    )

    try:
        response = requests.post(
            VULCAN_SENSOR_DATA_URL,
            json=payload,
            timeout=(
                connect_timeout,
                read_timeout,
            ),
        )

    except requests.ConnectTimeout as error:
        elapsed_seconds = (
            time.monotonic()
            - request_started_at
        )

        logger.error(
            (
                "Vulcan connection timed out: "
                "destination=%s, "
                "elapsed=%.2fs, "
                "error_type=%s"
            ),
            endpoint_name,
            elapsed_seconds,
            type(error).__name__,
        )

        return _create_failed_result(
            message=(
                "Vulcan connection timed out"
            ),
            payload=payload,
        )

    except requests.ReadTimeout as error:
        elapsed_seconds = (
            time.monotonic()
            - request_started_at
        )

        logger.error(
            (
                "Vulcan response timed out: "
                "destination=%s, "
                "elapsed=%.2fs, "
                "error_type=%s"
            ),
            endpoint_name,
            elapsed_seconds,
            type(error).__name__,
        )

        return _create_failed_result(
            message=(
                "Vulcan response timed out"
            ),
            payload=payload,
        )

    except requests.exceptions.SSLError as error:
        elapsed_seconds = (
            time.monotonic()
            - request_started_at
        )

        logger.error(
            (
                "Vulcan SSL connection failed: "
                "destination=%s, "
                "elapsed=%.2fs, "
                "error_type=%s, "
                "error=%s"
            ),
            endpoint_name,
            elapsed_seconds,
            type(error).__name__,
            error,
        )

        return _create_failed_result(
            message=(
                "Vulcan SSL connection failed"
            ),
            payload=payload,
        )

    except requests.ConnectionError as error:
        elapsed_seconds = (
            time.monotonic()
            - request_started_at
        )

        logger.error(
            (
                "Cannot connect to Vulcan API: "
                "destination=%s, "
                "elapsed=%.2fs, "
                "error_type=%s, "
                "error=%s"
            ),
            endpoint_name,
            elapsed_seconds,
            type(error).__name__,
            error,
        )

        return _create_failed_result(
            message=(
                "Cannot connect to Vulcan API"
            ),
            payload=payload,
        )

    except requests.Timeout as error:
        elapsed_seconds = (
            time.monotonic()
            - request_started_at
        )

        logger.error(
            (
                "Vulcan API request timed out: "
                "destination=%s, "
                "elapsed=%.2fs, "
                "error_type=%s"
            ),
            endpoint_name,
            elapsed_seconds,
            type(error).__name__,
        )

        return _create_failed_result(
            message=(
                "Vulcan API request timed out"
            ),
            payload=payload,
        )

    except requests.RequestException as error:
        elapsed_seconds = (
            time.monotonic()
            - request_started_at
        )

        logger.error(
            (
                "Unexpected Vulcan request error: "
                "destination=%s, "
                "elapsed=%.2fs, "
                "error_type=%s, "
                "error=%s"
            ),
            endpoint_name,
            elapsed_seconds,
            type(error).__name__,
            error,
        )

        return _create_failed_result(
            message=(
                "Unexpected Vulcan request error"
            ),
            payload=payload,
        )

    except Exception:
        elapsed_seconds = (
            time.monotonic()
            - request_started_at
        )

        logger.exception(
            (
                "Unexpected error while sending "
                "data to Vulcan: "
                "destination=%s, "
                "elapsed=%.2fs"
            ),
            endpoint_name,
            elapsed_seconds,
        )

        return _create_failed_result(
            message=(
                "Unexpected error while sending "
                "data to Vulcan"
            ),
            payload=payload,
        )

    elapsed_seconds = (
        time.monotonic()
        - request_started_at
    )

    logger.info(
        (
            "Vulcan API response received: "
            "destination=%s, "
            "status_code=%d, "
            "elapsed=%.2fs"
        ),
        endpoint_name,
        response.status_code,
        elapsed_seconds,
    )

    try:
        response_data = (
            response.json()
        )

    except ValueError:
        response_data = (
            response.text
        )

    if not response.ok:
        logger.error(
            (
                "Vulcan API returned an error: "
                "destination=%s, "
                "status_code=%d, "
                "elapsed=%.2fs"
            ),
            endpoint_name,
            response.status_code,
            elapsed_seconds,
        )

        return _create_failed_result(
            message=(
                "Vulcan API returned an error"
            ),
            payload=payload,
            status_code=response.status_code,
            response=response_data,
        )

    logger.info(
        (
            "Successfully sent sensor data "
            "to Vulcan: "
            "destination=%s, "
            "sensor_count=%d, "
            "status_code=%d, "
            "elapsed=%.2fs"
        ),
        endpoint_name,
        len(sensor_values),
        response.status_code,
        elapsed_seconds,
    )

    return {
        "ok": True,
        "message": (
            "Sensor values sent to Vulcan"
        ),
        "status_code": response.status_code,
        "payload": payload,
        "response": response_data,
    }