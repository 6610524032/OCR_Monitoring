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


def process_once():
    queue_items = claim_queue()

    if not queue_items:
        return

    sensor_groups = defaultdict(list)
    queue_id_groups = defaultdict(list)

    for item in queue_items:
        sensor_api_key = str(
            item.get("sensor_api_key", "")
        ).strip()

        if not sensor_api_key:
            logger.warning(
                "Queue ID %s does not have a sensor API key",
                item["id"]
            )

            mark_failed(
                queue_ids=[item["id"]],
                result={
                    "message": (
                        "Queue item does not have "
                        "a sensor API key"
                    ),
                    "status_code": None,
                    "response": None
                }
            )

            continue

        sensor_groups[sensor_api_key].append({
            "sensor_api_key": sensor_api_key,
            "capture_timestamp": item[
                "capture_timestamp"
            ],
            "value": item["value"]
        })

        queue_id_groups[sensor_api_key].append(
            item["id"]
        )

    for sensor_api_key, sensor_values in (
        sensor_groups.items()
    ):
        queue_ids = queue_id_groups[
            sensor_api_key
        ]

        result = send_sensor_values_to_vulcan(
            sensor_values
        )

        if result.get("ok"):
            mark_sent(
                queue_ids=queue_ids,
                result=result
            )

            logger.info(
                "Sent %d sensor value(s) to Vulcan",
                len(sensor_values)
            )

        else:
            mark_failed(
                queue_ids=queue_ids,
                result=result
            )

            logger.error(
                "Vulcan send failed: %s",
                result.get(
                    "message",
                    "Unknown error"
                )
            )


def sender_loop():
    logger.info(
        "Sender Worker started"
    )

    while True:
        try:
            process_once()

        except Exception:
            logger.exception(
                "Unexpected sender worker error"
            )

        time.sleep(
            POLL_INTERVAL_SECONDS
        )


if __name__ == "__main__":
    sender_loop()