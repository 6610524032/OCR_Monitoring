import copy
import json
import requests
from threading import Lock
from time import monotonic

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

MAX_GET_CACHE_ITEMS = 256
MAX_GET_CACHE_AGE_SECONDS = 3600


QUIET_SUCCESS_PATHS = {
    "/api/worker/outbound-queue/claim",
}


_get_cache_lock = Lock()
_get_response_cache = {}


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


def _cache_key(
    api_path,
    params,
):
    try:
        normalized_params = json.dumps(
            params or {},
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
            ensure_ascii=True,
            default=str,
        )

    except (
        TypeError,
        ValueError,
    ):
        normalized_params = repr(
            params
        )

    return (
        str(
            api_path
        ),
        normalized_params,
    )


def _store_get_response(
    api_path,
    params,
    result,
):
    if not isinstance(
        result,
        dict,
    ):
        return

    if result.get(
        "ok"
    ) is False:
        return

    key = _cache_key(
        api_path,
        params,
    )

    stored_at = monotonic()

    with _get_cache_lock:
        if (
            key not in _get_response_cache
            and len(
                _get_response_cache
            ) >= MAX_GET_CACHE_ITEMS
        ):
            oldest_key = min(
                _get_response_cache,
                key=lambda current_key: (
                    _get_response_cache[
                        current_key
                    ][0]
                ),
            )

            _get_response_cache.pop(
                oldest_key,
                None,
            )

        _get_response_cache[
            key
        ] = (
            stored_at,
            copy.deepcopy(
                result
            ),
        )


def _load_cached_get_response(
    api_path,
    params,
):
    key = _cache_key(
        api_path,
        params,
    )

    current_time = monotonic()

    with _get_cache_lock:
        cached_item = (
            _get_response_cache.get(
                key
            )
        )

        if cached_item is None:
            return (
                None,
                None,
            )

        stored_at, result = (
            cached_item
        )

        age_seconds = max(
            0.0,
            current_time - stored_at,
        )

        if (
            age_seconds
            > MAX_GET_CACHE_AGE_SECONDS
        ):
            _get_response_cache.pop(
                key,
                None,
            )

            return (
                None,
                None,
            )

        return (
            copy.deepcopy(
                result
            ),
            age_seconds,
        )


def _get_cached_fallback(
    method,
    api_path,
    params,
    reason,
):
    if method != "GET":
        return None

    cached_result, age_seconds = (
        _load_cached_get_response(
            api_path,
            params,
        )
    )

    if cached_result is None:
        return None

    logger.warning(
        (
            "Using cached API response: "
            "method=%s, path=%s, "
            "age_seconds=%.1f, reason=%s"
        ),
        method,
        api_path,
        age_seconds,
        reason,
    )

    return cached_result


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
    method = str(
        method
    ).upper()

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

        if method == "GET":
            _store_get_response(
                api_path=api_path,
                params=params,
                result=result,
            )

        log_request_success(
            method=method,
            api_path=api_path,
            status_code=(
                response.status_code
            ),
        )

        return result

    except requests.Timeout as error:
        cached_result = (
            _get_cached_fallback(
                method=method,
                api_path=api_path,
                params=params,
                reason="timeout",
            )
        )

        if cached_result is not None:
            return cached_result

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
        cached_result = (
            _get_cached_fallback(
                method=method,
                api_path=api_path,
                params=params,
                reason=(
                    "connection error"
                ),
            )
        )

        if cached_result is not None:
            return cached_result

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
            method == "GET"
            and status_code is not None
            and status_code >= 500
        ):
            cached_result = (
                _get_cached_fallback(
                    method=method,
                    api_path=api_path,
                    params=params,
                    reason=(
                        f"HTTP {status_code}"
                    ),
                )
            )

            if cached_result is not None:
                return cached_result

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
        cached_result = (
            _get_cached_fallback(
                method=method,
                api_path=api_path,
                params=params,
                reason=(
                    "request error"
                ),
            )
        )

        if cached_result is not None:
            return cached_result

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
        cached_result = (
            _get_cached_fallback(
                method=method,
                api_path=api_path,
                params=params,
                reason=(
                    "invalid API response"
                ),
            )
        )

        if cached_result is not None:
            return cached_result

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