import time
from collections import defaultdict

from src.logger import create_logger
from src.server.api_client import (
    ApiClientError,
    api_post
)
from src.server.integrations.vulcan_client import (
    send_sensor_values_to_vulcan
)


logger = create_logger(
    "processing.sender_worker"
)


POLL_INTERVAL_SECONDS = 5
BATCH_SIZE = 100


def claim_queue(limit=BATCH_SIZE):
    response = api_post(
        "/api/worker/outbound-queue/claim",
        payload={
            "limit": limit
        }
    )

    if not response.get("ok"):
        logger.error(
            "Cannot claim outbound queue: %s",
            response.get(
                "message",
                "Unknown error"
            )
        )

        raise ApiClientError(
            response.get(
                "message",
                "Cannot claim queue"
            )
        )

    queue_items = response.get(
        "queue_items",
        []
    )

    if queue_items:
        logger.info(
            "Claimed %d outbound queue item(s)",
            len(queue_items)
        )

    return queue_items


def mark_sent(queue_ids, result):
    response = api_post(
        "/api/worker/outbound-queue/sent",
        payload={
            "queue_ids": queue_ids,
            "http_status": result.get(
                "status_code"
            ),
            "response_message": str(
                result.get("response")
            )
        }
    )

    if not response.get("ok"):
        logger.error(
            "Cannot mark queue as sent: %s",
            response.get(
                "message",
                "Unknown error"
            )
        )

        raise ApiClientError(
            response.get(
                "message",
                "Cannot mark queue as sent"
            )
        )

    logger.info(
        "Marked %d queue item(s) as sent",
        len(queue_ids)
    )


def mark_failed(queue_ids, result):
    response = api_post(
        "/api/worker/outbound-queue/failed",
        payload={
            "queue_ids": queue_ids,
            "error_message": result.get(
                "message",
                ""
            ),
            "http_status": result.get(
                "status_code"
            ),
            "response_message": str(
                result.get("response")
            )
        }
    )

    if not response.get("ok"):
        logger.error(
            "Cannot mark queue as failed: %s",
            response.get(
                "message",
                "Unknown error"
            )
        )

        raise ApiClientError(
            response.get(
                "message",
                "Cannot mark queue as failed"
            )
        )

    logger.warning(
        "Marked %d queue item(s) as failed",
        len(queue_ids)
    )

def safe_mark_failed(
    queue_ids,
    result,
):
    try:
        mark_failed(
            queue_ids=queue_ids,
            result=result,
        )

    except Exception:
        logger.exception(
            (
                "Cannot mark queue item(s) "
                "as failed: queue_ids=%s"
            ),
            queue_ids,
        )

def process_once():
    queue_items = claim_queue()

    if not queue_items:
        return

    if not isinstance(
        queue_items,
        list,
    ):
        logger.error(
            (
                "Outbound queue API returned "
                "invalid queue data: %r"
            ),
            queue_items,
        )

        return

    sensor_groups = defaultdict(list)
    queue_id_groups = defaultdict(list)

    for item in queue_items:
        try:
            if not isinstance(
                item,
                dict,
            ):
                logger.error(
                    (
                        "Invalid outbound queue "
                        "item: %r"
                    ),
                    item,
                )

                continue

            queue_id = item.get("id")

            if queue_id is None:
                logger.error(
                    (
                        "Outbound queue item "
                        "does not contain an ID: %r"
                    ),
                    item,
                )

                continue

            sensor_api_key = str(
                item.get(
                    "sensor_api_key",
                    "",
                )
            ).strip()

            if not sensor_api_key:
                logger.warning(
                    (
                        "Queue ID %s does not have "
                        "a sensor API key"
                    ),
                    queue_id,
                )

                safe_mark_failed(
                    queue_ids=[
                        queue_id
                    ],
                    result={
                        "message": (
                            "Queue item does not "
                            "have a sensor API key"
                        ),
                        "status_code": None,
                        "response": None,
                    },
                )

                continue

            capture_timestamp = (
                item.get(
                    "capture_timestamp"
                )
            )

            value = item.get(
                "value"
            )

            if capture_timestamp is None:
                logger.warning(
                    (
                        "Queue ID %s does not have "
                        "a capture timestamp"
                    ),
                    queue_id,
                )

                safe_mark_failed(
                    queue_ids=[
                        queue_id
                    ],
                    result={
                        "message": (
                            "Queue item does not "
                            "have a capture timestamp"
                        ),
                        "status_code": None,
                        "response": None,
                    },
                )

                continue

            if value is None:
                logger.warning(
                    (
                        "Queue ID %s does not have "
                        "a sensor value"
                    ),
                    queue_id,
                )

                safe_mark_failed(
                    queue_ids=[
                        queue_id
                    ],
                    result={
                        "message": (
                            "Queue item does not "
                            "have a sensor value"
                        ),
                        "status_code": None,
                        "response": None,
                    },
                )

                continue

            sensor_groups[
                sensor_api_key
            ].append({
                "sensor_api_key": (
                    sensor_api_key
                ),
                "capture_timestamp": (
                    capture_timestamp
                ),
                "value": value,
            })

            queue_id_groups[
                sensor_api_key
            ].append(
                queue_id
            )

        except Exception:
            logger.exception(
                (
                    "Unexpected error while "
                    "preparing outbound queue item"
                )
            )

            continue

    for sensor_api_key, sensor_values in (
        sensor_groups.items()
    ):
        queue_ids = queue_id_groups.get(
            sensor_api_key,
            [],
        )

        if not queue_ids:
            logger.warning(
                (
                    "Skipping Vulcan group because "
                    "queue IDs are missing: "
                    "sensor_api_key=%s"
                ),
                sensor_api_key,
            )

            continue

        try:
            result = (
                send_sensor_values_to_vulcan(
                    sensor_values
                )
            )

        except Exception as error:
            logger.exception(
                (
                    "Unexpected Vulcan send error: "
                    "sensor_api_key=%s, "
                    "queue_ids=%s"
                ),
                sensor_api_key,
                queue_ids,
            )

            safe_mark_failed(
                queue_ids=queue_ids,
                result={
                    "message": str(error),
                    "status_code": None,
                    "response": None,
                },
            )

            continue

        if not isinstance(
            result,
            dict,
        ):
            logger.error(
                (
                    "Vulcan client returned an "
                    "invalid result: %r"
                ),
                result,
            )

            safe_mark_failed(
                queue_ids=queue_ids,
                result={
                    "message": (
                        "Vulcan client returned "
                        "an invalid result"
                    ),
                    "status_code": None,
                    "response": result,
                },
            )

            continue

        if result.get("ok"):
            try:
                mark_sent(
                    queue_ids=queue_ids,
                    result=result,
                )

            except Exception:
                logger.exception(
                    (
                        "Data was sent to Vulcan, "
                        "but queue status could not "
                        "be marked as sent: "
                        "queue_ids=%s"
                    ),
                    queue_ids,
                )

                # ไม่ mark_failed เพราะข้อมูลถูกส่ง
                # ไปยัง Vulcan สำเร็จแล้ว
                continue

            logger.info(
                (
                    "Sent %d sensor value(s) "
                    "to Vulcan"
                ),
                len(sensor_values),
            )

            continue

        safe_mark_failed(
            queue_ids=queue_ids,
            result=result,
        )

        logger.error(
            (
                "Vulcan send failed: "
                "sensor_api_key=%s, "
                "message=%s"
            ),
            sensor_api_key,
            result.get(
                "message",
                "Unknown error",
            ),
        )


def sender_loop():
    logger.info(
        "Sender Worker started"
    )

    while True:
        try:
            process_once()

        except ApiClientError:
            logger.exception(
                (
                    "Sender Worker cannot "
                    "connect to queue API"
                )
            )

        except Exception:
            logger.exception(
                (
                    "Unexpected sender "
                    "worker error"
                )
            )

        try:
            time.sleep(
                POLL_INTERVAL_SECONDS
            )

        except KeyboardInterrupt:
            logger.info(
                (
                    "Sender Worker stopped "
                    "by user"
                )
            )

            break


if __name__ == "__main__":
    sender_loop()