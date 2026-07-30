from dataclasses import dataclass
from functools import lru_cache
from threading import RLock
from time import monotonic
from typing import Any
from urllib.parse import quote

from src.logger import create_logger
from src.server.api_client import (
    ApiClientError,
    api_get,
)


logger = create_logger(
    "server.camera_client"
)


CAMERA_CONFIG_API_PATH = (
    "/api/camera/config"
)

API_WARNING_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class CameraConfig:
    camera_name: str
    camera_ip: str
    camera_port: int
    camera_username: str
    camera_password: str
    rtsp_path: str
    rtsp_url: str


class CameraConfigError(RuntimeError):
    """
    Raised when camera configuration
    cannot be loaded or validated.
    """


class CameraNotConfiguredError(
    CameraConfigError
):
    """
    Raised when no active camera
    configuration exists.

    This is a normal configuration state,
    not a system failure.
    """


_cache_lock = RLock()
_last_camera_config: (
    CameraConfig | None
) = None
_last_api_warning_at = 0.0


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    text = str(
        value or ""
    ).strip()

    if not text:
        raise CameraConfigError(
            f"{field_name} is required"
        )

    return text


def _normalize_camera_port(
    value: Any,
) -> int:
    try:
        camera_port = int(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise CameraConfigError(
            "camera_port must be an integer"
        ) from error

    if not (
        1 <= camera_port <= 65535
    ):
        raise CameraConfigError(
            (
                "camera_port must be "
                "between 1 and 65535"
            )
        )

    return camera_port


def _get_http_status(
    error: BaseException,
) -> int | None:
    """
    Extract an HTTP status from the original
    requests exception when available.
    """
    cause = error.__cause__

    response = getattr(
        cause,
        "response",
        None,
    )

    status_code = getattr(
        response,
        "status_code",
        None,
    )

    if status_code is None:
        return None

    try:
        return int(
            status_code
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return None


def _get_last_camera_config(
) -> CameraConfig | None:
    with _cache_lock:
        return _last_camera_config


def _set_last_camera_config(
    camera: CameraConfig | None,
) -> None:
    global _last_camera_config

    with _cache_lock:
        _last_camera_config = camera


def _log_api_warning(
    message: str,
    *args,
) -> None:
    """
    Avoid writing the same API warning
    every few seconds.
    """
    global _last_api_warning_at

    current_time = monotonic()

    with _cache_lock:
        elapsed = (
            current_time
            - _last_api_warning_at
        )

        if (
            _last_api_warning_at > 0
            and elapsed
            < API_WARNING_INTERVAL_SECONDS
        ):
            return

        _last_api_warning_at = (
            current_time
        )

    logger.warning(
        message,
        *args,
    )


def build_rtsp_url(
    camera_ip: str,
    camera_port: int,
    camera_username: str,
    camera_password: str,
    rtsp_path: str,
) -> str:
    normalized_ip = _required_text(
        camera_ip,
        "camera_ip",
    )

    normalized_username = (
        _required_text(
            camera_username,
            "camera_username",
        )
    )

    normalized_password = (
        _required_text(
            camera_password,
            "camera_password",
        )
    )

    normalized_path = _required_text(
        rtsp_path,
        "rtsp_path",
    )

    normalized_port = (
        _normalize_camera_port(
            camera_port
        )
    )

    lower_ip = (
        normalized_ip.lower()
    )

    if lower_ip.startswith(
        (
            "rtsp://",
            "http://",
            "https://",
        )
    ):
        raise CameraConfigError(
            (
                "camera_ip must contain only "
                "an IP address or hostname"
            )
        )

    if not normalized_path.startswith(
        "/"
    ):
        normalized_path = (
            "/"
            + normalized_path
        )

    encoded_username = quote(
        normalized_username,
        safe="",
    )

    encoded_password = quote(
        normalized_password,
        safe="",
    )

    # Support IPv6 addresses without changing
    # normal IPv4 addresses or hostnames.
    if (
        ":" in normalized_ip
        and not normalized_ip.startswith(
            "["
        )
    ):
        normalized_host = (
            f"[{normalized_ip}]"
        )

    else:
        normalized_host = (
            normalized_ip
        )

    logger.debug(
        (
            "RTSP URL prepared for "
            "camera host %s:%d"
        ),
        normalized_host,
        normalized_port,
    )

    return (
        f"rtsp://"
        f"{encoded_username}:"
        f"{encoded_password}"
        f"@{normalized_host}:"
        f"{normalized_port}"
        f"{normalized_path}"
    )


def _build_camera_config(
    camera: dict[str, Any],
) -> CameraConfig:
    camera_name = _required_text(
        camera.get(
            "camera_name"
        ),
        "camera_name",
    )

    camera_ip = _required_text(
        camera.get(
            "camera_ip"
        ),
        "camera_ip",
    )

    camera_port = (
        _normalize_camera_port(
            camera.get(
                "camera_port",
                554,
            )
        )
    )

    camera_username = (
        _required_text(
            camera.get(
                "camera_username"
            ),
            "camera_username",
        )
    )

    camera_password = (
        _required_text(
            camera.get(
                "camera_password"
            ),
            "camera_password",
        )
    )

    rtsp_path = _required_text(
        camera.get(
            "rtsp_path"
        ),
        "rtsp_path",
    )

    if not rtsp_path.startswith(
        "/"
    ):
        rtsp_path = (
            "/"
            + rtsp_path
        )

    rtsp_url = build_rtsp_url(
        camera_ip=camera_ip,
        camera_port=camera_port,
        camera_username=(
            camera_username
        ),
        camera_password=(
            camera_password
        ),
        rtsp_path=rtsp_path,
    )

    return CameraConfig(
        camera_name=camera_name,
        camera_ip=camera_ip,
        camera_port=camera_port,
        camera_username=(
            camera_username
        ),
        camera_password=(
            camera_password
        ),
        rtsp_path=rtsp_path,
        rtsp_url=rtsp_url,
    )


def fetch_camera_config(
) -> CameraConfig:
    logger.debug(
        "Loading camera configuration"
    )

    try:
        result = api_get(
            CAMERA_CONFIG_API_PATH
        )

    except ApiClientError as error:
        status_code = (
            _get_http_status(
                error
            )
        )

        # Compatibility with an older API
        # version that returned HTTP 404 when
        # no camera was configured.
        if status_code == 404:
            _set_last_camera_config(
                None
            )

            raise (
                CameraNotConfiguredError(
                    (
                        "Camera configuration "
                        "has not been set"
                    )
                )
            ) from error

        cached_camera = (
            _get_last_camera_config()
        )

        if cached_camera is not None:
            _log_api_warning(
                (
                    "Camera configuration API "
                    "is unavailable; using the "
                    "last cached configuration"
                )
            )

            return cached_camera

        _log_api_warning(
            (
                "Cannot load camera "
                "configuration from API: %s"
            ),
            error,
        )

        raise CameraConfigError(
            (
                "Cannot load camera "
                "configuration from API"
            )
        ) from error

    if not isinstance(
        result,
        dict,
    ):
        raise CameraConfigError(
            (
                "Camera configuration API "
                "returned an invalid response"
            )
        )

    configured = result.get(
        "configured"
    )

    camera = result.get(
        "camera"
    )

    # Current API response when the user
    # has not configured a camera yet.
    if (
        configured is False
        or (
            camera is None
            and result.get(
                "ok"
            ) is False
        )
    ):
        _set_last_camera_config(
            None
        )

        message = str(
            result.get(
                "message",
                (
                    "Camera configuration "
                    "has not been set"
                ),
            )
        ).strip()

        raise CameraNotConfiguredError(
            message
            or (
                "Camera configuration "
                "has not been set"
            )
        )

    if not result.get(
        "ok"
    ):
        message = str(
            result.get(
                "message",
                (
                    "Camera configuration "
                    "request failed"
                ),
            )
        ).strip()

        raise CameraConfigError(
            message
            or (
                "Camera configuration "
                "request failed"
            )
        )

    if not isinstance(
        camera,
        dict,
    ):
        raise CameraConfigError(
            (
                "Camera configuration API "
                "did not return a camera object"
            )
        )

    camera_config = (
        _build_camera_config(
            camera
        )
    )

    _set_last_camera_config(
        camera_config
    )

    logger.debug(
        (
            "Camera configuration loaded "
            "successfully: camera=%s"
        ),
        camera_config.camera_name,
    )

    return camera_config


@lru_cache(
    maxsize=1
)
def get_camera_config(
) -> CameraConfig:
    """
    Return the in-process cached configuration.

    Exceptions are not stored by lru_cache,
    so a later request can try the API again.
    """
    return fetch_camera_config()


def reload_camera_config(
) -> CameraConfig:
    """
    Refresh the configuration from the API.

    The last successfully loaded configuration
    remains available as a fallback when the
    API is temporarily unreachable.
    """
    get_camera_config.cache_clear()

    return get_camera_config()


def clear_camera_config_cache(
) -> None:
    """
    Completely remove both configuration caches.

    This may be called after explicitly deleting
    or resetting the camera configuration.
    """
    get_camera_config.cache_clear()

    _set_last_camera_config(
        None
    )

    logger.debug(
        "Camera configuration cache cleared"
    )