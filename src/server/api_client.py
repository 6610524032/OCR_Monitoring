import requests

from src.logger import create_logger
from src.server.config import (
    API_KEY,
    API_SERVER_URL,
)


logger = create_logger(
    "server.api_client"
)


DEFAULT_TIMEOUT = 30


class ApiClientError(RuntimeError):
    """Raised when the API server cannot complete a request."""


def build_api_url(api_path):
    return (
        f"{API_SERVER_URL.rstrip('/')}/"
        f"{api_path.lstrip('/')}"
    )


def build_headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


def api_get(
    api_path,
    params=None,
    timeout=DEFAULT_TIMEOUT,
):
    url = build_api_url(api_path)

    try:
        response = requests.get(
            url,
            headers=build_headers(),
            params=params,
            timeout=timeout,
        )

        response.raise_for_status()

        logger.info(
            "GET %s succeeded",
            api_path,
        )

        return response.json()

    except requests.RequestException as error:
        logger.error(
            "GET %s failed: %s",
            api_path,
            error,
        )

        raise ApiClientError(
            f"GET request failed: {url}: {error}"
        ) from error

    except ValueError as error:
        logger.error(
            "GET %s returned invalid JSON",
            api_path,
        )

        raise ApiClientError(
            f"Invalid JSON response from: {url}"
        ) from error


def api_post(
    api_path,
    payload=None,
    timeout=DEFAULT_TIMEOUT,
):
    url = build_api_url(api_path)

    try:
        response = requests.post(
            url,
            headers=build_headers(),
            json=payload or {},
            timeout=timeout,
        )

        response.raise_for_status()

        logger.info(
            "POST %s succeeded",
            api_path,
        )

        return response.json()

    except requests.RequestException as error:
        logger.error(
            "POST %s failed: %s",
            api_path,
            error,
        )

        raise ApiClientError(
            f"POST request failed: {url}: {error}"
        ) from error

    except ValueError as error:
        logger.error(
            "POST %s returned invalid JSON",
            api_path,
        )

        raise ApiClientError(
            f"Invalid JSON response from: {url}"
        ) from error