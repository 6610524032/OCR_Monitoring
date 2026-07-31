import requests

from src.logger import create_logger
from src.server.config import (
    API_KEY,
    API_SERVER_URL,
)


logger = create_logger(
    "server.api_client"
)


DEFAULT_CONNECT_TIMEOUT = 5
DEFAULT_READ_TIMEOUT = 30

DEFAULT_TIMEOUT = (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
)

MAX_ERROR_MESSAGE_LENGTH = 300


QUIET_SUCCESS_PATHS = {
    "/api/worker/outbound-queue/claim",
}


class ApiClientError(RuntimeError):
    """
    Raised when the API server cannot
    complete a request safely.
    """


def build_api_url(api_path):
    return (
        f"{API_SERVER_URL.rstrip('/')}/"
        f"{api_path.lstrip('/')}"
    )


def build_headers():
    return {
        "Authorization": (
            f"Bearer {API_KEY}"
        ),
        "Content-Type": (
            "application/json"
        ),
    }


def log_request_success(
    method,
    api_path,
    status_code,
):
    log_method = (
        logger.debug
        if api_path in QUIET_SUCCESS_PATHS
        else logger.info
    )

    log_method(
        (
            "%s %s succeeded: "
            "status=%s"
        ),
        method,
        api_path,
        status_code,
    )


def get_response_error_message(
    response,
):
    try:
        result = response.json()

        if isinstance(
            result,
            dict,
        ):
            message = (
                result.get("message")
                or result.get("error")
                or ""
            )

        else:
            message = str(
                result
            )

    except ValueError:
        message = str(
            response.text or ""
        ).strip()

    if not message:
        message = (
            response.reason
            or "Unknown API error"
        )

    return str(
        message
    )[
        :MAX_ERROR_MESSAGE_LENGTH
    ]


def parse_json_response(
    response,
    method,
    api_path,
):
    try:
        result = response.json()

    except ValueError as error:
        logger.error(
            (
                "%s %s returned invalid JSON: "
                "status=%s, content_type=%s"
            ),
            method,
            api_path,
            response.status_code,
            response.headers.get(
                "Content-Type",
                "",
            ),
        )

        raise ApiClientError(
            (
                f"{method} {api_path} "
                "returned invalid JSON"
            )
        ) from error

    if not isinstance(
        result,
        dict,
    ):
        logger.error(
            (
                "%s %s returned unexpected "
                "JSON type: %s"
            ),
            method,
            api_path,
            type(result).__name__,
        )

        raise ApiClientError(
            (
                f"{method} {api_path} "
                "returned invalid response data"
            )
        )

    return result


def send_api_request(
    method,
    api_path,
    params=None,
    payload=None,
    timeout=DEFAULT_TIMEOUT,
):
    url = build_api_url(
        api_path
    )

    request_options = {
        "method": method,
        "url": url,
        "headers": build_headers(),
        "timeout": timeout,
    }

    if params is not None:
        request_options[
            "params"
        ] = params

    if method == "POST":
        request_options[
            "json"
        ] = (
            payload
            if payload is not None
            else {}
        )

    response = None

    try:
        response = requests.request(
            **request_options
        )

        response.raise_for_status()

        result = parse_json_response(
            response=response,
            method=method,
            api_path=api_path,
        )

        # ใช้ DEBUG แทน INFO เพื่อไม่ให้
        # Queue polling ทุก 5 วินาทีทำให้ Log โตเร็ว
        log_request_success(
            method=method,
            api_path=api_path,
            status_code=response.status_code,
        )

        return result

    except requests.Timeout as error:
        logger.warning(
            (
                "%s %s timed out "
                "after %s"
            ),
            method,
            api_path,
            timeout,
        )

        raise ApiClientError(
            (
                f"{method} {api_path} "
                "timed out"
            )
        ) from error

    except requests.ConnectionError as error:
        logger.warning(
            (
                "%s %s cannot connect "
                "to API server"
            ),
            method,
            api_path,
        )

        raise ApiClientError(
            (
                f"{method} {api_path} "
                "cannot connect to API server"
            )
        ) from error

    except requests.HTTPError as error:
        status_code = (
            response.status_code
            if response is not None
            else None
        )

        response_message = (
            get_response_error_message(
                response
            )
            if response is not None
            else "Unknown API error"
        )

        if (
            status_code is not None
            and 400 <= status_code < 500
        ):
            logger.warning(
                (
                    "%s %s returned HTTP %s: %s"
                ),
                method,
                api_path,
                status_code,
                response_message,
            )

        else:
            logger.error(
                (
                    "%s %s returned HTTP %s: %s"
                ),
                method,
                api_path,
                status_code,
                response_message,
            )

        raise ApiClientError(
            (
                f"{method} {api_path} "
                f"returned HTTP {status_code}: "
                f"{response_message}"
            )
        ) from error

    except requests.RequestException as error:
        logger.exception(
            (
                "%s %s request failed"
            ),
            method,
            api_path,
        )

        raise ApiClientError(
            (
                f"{method} {api_path} "
                "request failed"
            )
        ) from error

    except ApiClientError:
        # Error จากการตรวจ JSON
        # ถูกจัดรูปแบบไว้แล้ว
        raise

    except Exception as error:
        logger.exception(
            (
                "Unexpected %s API request "
                "error: path=%s"
            ),
            method,
            api_path,
        )

        raise ApiClientError(
            (
                f"Unexpected {method} "
                f"request error: {api_path}"
            )
        ) from error

    finally:
        if response is not None:
            response.close()


def api_get(
    api_path,
    params=None,
    timeout=DEFAULT_TIMEOUT,
):
    return send_api_request(
        method="GET",
        api_path=api_path,
        params=params,
        timeout=timeout,
    )


def api_post(
    api_path,
    payload=None,
    timeout=DEFAULT_TIMEOUT,
):
    return send_api_request(
        method="POST",
        api_path=api_path,
        payload=payload,
        timeout=timeout,
    )