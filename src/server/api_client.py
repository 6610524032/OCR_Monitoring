import requests

from src.server.config import (
    API_KEY,
    API_SERVER_URL
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
        "Content-Type": "application/json"
    }


def api_get(api_path, params=None, timeout=DEFAULT_TIMEOUT):
    url = build_api_url(api_path)

    try:
        response = requests.get(
            url,
            headers=build_headers(),
            params=params,
            timeout=timeout
        )

        response.raise_for_status()
        return response.json()

    except requests.RequestException as error:
        raise ApiClientError(
            f"GET request failed: {url}: {error}"
        ) from error

    except ValueError as error:
        raise ApiClientError(
            f"Invalid JSON response from: {url}"
        ) from error


def api_post(api_path, payload=None, timeout=DEFAULT_TIMEOUT):
    url = build_api_url(api_path)

    try:
        response = requests.post(
            url,
            headers=build_headers(),
            json=payload or {},
            timeout=timeout
        )

        response.raise_for_status()
        return response.json()

    except requests.RequestException as error:
        raise ApiClientError(
            f"POST request failed: {url}: {error}"
        ) from error

    except ValueError as error:
        raise ApiClientError(
            f"Invalid JSON response from: {url}"
        ) from error