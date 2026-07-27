from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote

from src.logger import create_logger
from src.server.api_client import (
    ApiClientError,
    api_get,
)


logger = create_logger(
    "server.camera_client"
)


CAMERA_CONFIG_API_PATH = "/api/camera/config"


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
    """Raised when camera configuration cannot be loaded."""


def build_rtsp_url(
    camera_ip: str,
    camera_port: int,
    camera_username: str,
    camera_password: str,
    rtsp_path: str,
) -> str:
    camera_ip = str(camera_ip).strip()
    camera_username = str(camera_username).strip()
    camera_password = str(camera_password).strip()
    rtsp_path = str(rtsp_path).strip()

    if not camera_ip:
        logger.error("camera_ip is missing")
        raise CameraConfigError(
            "camera_ip is missing"
        )

    if not camera_username:
        logger.error("camera_username is missing")
        raise CameraConfigError(
            "camera_username is missing"
        )

    if not camera_password:
        logger.error("camera_password is missing")
        raise CameraConfigError(
            "camera_password is missing"
        )

    if not rtsp_path:
        logger.error("rtsp_path is missing")
        raise CameraConfigError(
            "rtsp_path is missing"
        )

    if not rtsp_path.startswith("/"):
        rtsp_path = "/" + rtsp_path

    username = quote(
        camera_username,
        safe="",
    )

    password = quote(
        camera_password,
        safe="",
    )

    logger.info(
        "RTSP URL built for camera %s:%s",
        camera_ip,
        camera_port,
    )

    return (
        f"rtsp://{username}:{password}"
        f"@{camera_ip}:{camera_port}{rtsp_path}"
    )


def fetch_camera_config() -> CameraConfig:
    logger.info(
        "Loading camera configuration"
    )

    try:
        result = api_get(
            CAMERA_CONFIG_API_PATH
        )

    except ApiClientError:
        logger.exception(
            "Cannot load camera configuration from API"
        )
        raise CameraConfigError(
            "Cannot load camera configuration from API"
        )

    if not result.get("ok"):
        message = result.get(
            "message",
            "Camera configuration request failed",
        )

        logger.error(
            "Camera configuration request failed: %s",
            message,
        )

        raise CameraConfigError(
            message
        )

    camera = result.get("camera")

    if not isinstance(camera, dict):
        logger.error(
            "camera object is missing"
        )

        raise CameraConfigError(
            "camera object is missing"
        )

    camera_name = str(
        camera.get("camera_name", "")
    ).strip()

    camera_ip = str(
        camera.get("camera_ip", "")
    ).strip()

    camera_port = int(
        camera.get("camera_port", 554)
    )

    camera_username = str(
        camera.get("camera_username", "")
    ).strip()

    camera_password = str(
        camera.get("camera_password", "")
    ).strip()

    rtsp_path = str(
        camera.get("rtsp_path", "")
    ).strip()

    rtsp_url = build_rtsp_url(
        camera_ip=camera_ip,
        camera_port=camera_port,
        camera_username=camera_username,
        camera_password=camera_password,
        rtsp_path=rtsp_path,
    )

    logger.info(
        "Camera configuration loaded successfully"
    )

    return CameraConfig(
        camera_name=camera_name,
        camera_ip=camera_ip,
        camera_port=camera_port,
        camera_username=camera_username,
        camera_password=camera_password,
        rtsp_path=rtsp_path,
        rtsp_url=rtsp_url,
    )


@lru_cache(maxsize=1)
def get_camera_config() -> CameraConfig:
    return fetch_camera_config()


def reload_camera_config() -> CameraConfig:
    logger.info(
        "Reloading camera configuration"
    )

    get_camera_config.cache_clear()

    return get_camera_config()