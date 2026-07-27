from typing import Any

import requests

from src.logger import create_logger


logger = create_logger(
    "processing.vulcan_client"
)


VULCAN_SENSOR_DATA_URL = (
    "https://vulcan.mtec.or.th/"
    "api/points/sensor-data"
)

DEFAULT_TIMEOUT_SECONDS = 20


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

    for index, item in enumerate(sensor_values):
        api_key = str(
            item.get("sensor_api_key", "")
        ).strip()

        capture_timestamp = item.get(
            "capture_timestamp"
        )

        value = item.get("value")

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
                "Missing capture timestamp for sensor %d",
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

        except (TypeError, ValueError) as error:
            logger.error(
                "Invalid capture timestamp for sensor %d",
                index + 1,
            )

            raise ValueError(
                f"Invalid capture timestamp for "
                f"sensor number {index + 1}"
            ) from error

        try:
            numeric_value = float(
                value
            )

        except (TypeError, ValueError) as error:
            logger.error(
                "Invalid sensor value for sensor %d",
                index + 1,
            )

            raise ValueError(
                f"Invalid sensor value for "
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


def send_sensor_values_to_vulcan(
    sensor_values: list[dict[str, Any]],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """
    Build and send sensor values to Vulcan.
    """

    try:
        payload = build_vulcan_payload(
            sensor_values
        )

        logger.info(
            "Sending %d sensor(s) to Vulcan",
            len(sensor_values),
        )

        response = requests.post(
            VULCAN_SENSOR_DATA_URL,
            json=payload,
            timeout=timeout_seconds,
        )

    except ValueError as error:
        logger.error(
            "Cannot build Vulcan payload: %s",
            error,
        )

        return {
            "ok": False,
            "message": str(error),
            "status_code": None,
            "payload": None,
            "response": None,
        }

    except requests.Timeout:
        logger.error(
            "Vulcan API request timed out"
        )

        return {
            "ok": False,
            "message": (
                "Vulcan API request timed out"
            ),
            "status_code": None,
            "payload": payload,
            "response": None,
        }

    except requests.RequestException as error:
        logger.error(
            "Cannot connect to Vulcan API: %s",
            error,
        )

        return {
            "ok": False,
            "message": (
                "Cannot connect to Vulcan API: "
                f"{error}"
            ),
            "status_code": None,
            "payload": payload,
            "response": None,
        }

    try:
        response_data = response.json()

    except ValueError:
        response_data = response.text

    if not response.ok:
        logger.error(
            "Vulcan API returned HTTP %d",
            response.status_code,
        )

        return {
            "ok": False,
            "message": (
                "Vulcan API returned an error"
            ),
            "status_code": response.status_code,
            "payload": payload,
            "response": response_data,
        }

    logger.info(
        "Successfully sent %d sensor(s) to Vulcan",
        len(sensor_values),
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