import time
from collections import defaultdict

from app.server.api_client import (
    ApiClientError,
    api_post
)
from app.server.integrations.vulcan_client import (
    send_sensor_values_to_vulcan
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
        raise ApiClientError(
            response.get(
                "message",
                "Cannot claim queue"
            )
        )

    return response.get(
        "queue_items",
        []
    )


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
        raise ApiClientError(
            response.get(
                "message",
                "Cannot mark queue as sent"
            )
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
        raise ApiClientError(
            response.get(
                "message",
                "Cannot mark queue as failed"
            )
        )


def process_once():
    queue_items = claim_queue()

    if not queue_items:
        print("No outbound queue")
        return

    sensor_groups = defaultdict(list)
    queue_id_groups = defaultdict(list)

    for item in queue_items:
        sensor_api_key = str(
            item.get("sensor_api_key", "")
        ).strip()

        if not sensor_api_key:
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

            print(
                f"Sent {len(sensor_values)} "
                "sensor value(s) to Vulcan"
            )

        else:
            mark_failed(
                queue_ids=queue_ids,
                result=result
            )

            print(
                "[VULCAN SEND FAILED]",
                result.get(
                    "message",
                    "Unknown error"
                )
            )


def sender_loop():
    print("Sender Worker Started")

    while True:
        try:
            process_once()

        except Exception as error:
            print(
                "[SENDER ERROR]",
                type(error).__name__,
                str(error)
            )

        time.sleep(
            POLL_INTERVAL_SECONDS
        )


if __name__ == "__main__":
    sender_loop()