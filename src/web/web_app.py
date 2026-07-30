import copy
import json
import os
import re
import time
from datetime import timedelta
from pathlib import Path
from threading import Lock
from time import monotonic

import cv2
import numpy as np
import requests
from flask import (
    Flask,
    Response,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from werkzeug.exceptions import BadRequest

from src.logger import create_logger
from src.processing.calibration import get_latest_file
from src.server.camera_client import (
    CameraConfigError,
    CameraNotConfiguredError,
    reload_camera_config,
)
from src.server.config import (
    API_KEY,
    API_SERVER_URL,
    CALIBRATED_IMAGES_DIR,
    RAW_IMAGES_DIR,
)
from src.web.web_auth import (
    authenticate_login,
    clear_login_session,
    create_login_session,
    get_csrf_token,
    get_current_user,
    get_missing_login_environment,
    get_session_secret,
    is_safe_next_path,
    login_required,
    login_required_json,
    validate_csrf_token,
)


logger = create_logger(
    "web.app"
)


DEFAULT_API_TIMEOUT = (
    5,
    30,
)

LONG_API_TIMEOUT = (
    5,
    60,
)

MAX_PROXY_REQUEST_BYTES = (
    2 * 1024 * 1024
)

MAX_PROXY_RESPONSE_BYTES = (
    8 * 1024 * 1024
)

MAX_API_PATH_LENGTH = 512

PROXY_READ_CHUNK_SIZE = (
    64 * 1024
)

LIVE_RETRY_SECONDS = 5
LIVE_READ_RETRY_SECONDS = 0.2
LIVE_READ_FAILURE_LIMIT = 3
LIVE_WARNING_INTERVAL_SECONDS = 60

LIVE_OPEN_TIMEOUT_MSEC = 5000
LIVE_READ_TIMEOUT_MSEC = 5000

LIVE_PLACEHOLDER_WIDTH = 960
LIVE_PLACEHOLDER_HEIGHT = 540


_SAFE_API_SEGMENT = re.compile(
    r"^[A-Za-z0-9_-]+$"
)


_live_warning_lock = Lock()
_live_warning_times: dict[
    str,
    float,
] = {}

_settings_cache_lock = Lock()
_settings_cache = None


class ProxyResponseTooLargeError(
    RuntimeError
):
    """Raised when an API response exceeds the limit."""


def _environment_bool(
    name: str,
    default: bool = False,
) -> bool:
    raw_value = os.getenv(
        name
    )

    if raw_value is None:
        return default

    normalized = (
        raw_value
        .strip()
        .casefold()
    )

    if normalized in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    return default


def _environment_port(
    name: str,
    default: int,
) -> int:
    try:
        value = int(
            os.getenv(
                name,
                str(
                    default
                ),
            )
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return default

    if not 1 <= value <= 65535:
        return default

    return value


app = Flask(__name__)

app.config.update(
    SECRET_KEY=get_session_secret(),
    PERMANENT_SESSION_LIFETIME=(
        timedelta(
            hours=8
        )
    ),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        _environment_bool(
            "WEB_SESSION_COOKIE_SECURE",
            default=False,
        )
    ),
    SESSION_REFRESH_EACH_REQUEST=False,
    MAX_CONTENT_LENGTH=(
        MAX_PROXY_REQUEST_BYTES
    ),
)


missing_login_environment = (
    get_missing_login_environment()
)

if missing_login_environment:
    logger.error(
        (
            "Web login environment is "
            "incomplete. Missing: %s"
        ),
        ", ".join(
            missing_login_environment
        ),
    )


@app.before_request
def load_current_user():
    g.current_user = (
        get_current_user()
    )


@app.after_request
def add_security_headers(
    response,
):
    response.headers.setdefault(
        "X-Content-Type-Options",
        "nosniff",
    )

    response.headers.setdefault(
        "X-Frame-Options",
        "SAMEORIGIN",
    )

    response.headers.setdefault(
        "Referrer-Policy",
        "same-origin",
    )

    response.headers.setdefault(
        "Cross-Origin-Resource-Policy",
        "same-origin",
    )

    if request.endpoint != "static":
        response.headers.setdefault(
            "Cache-Control",
            "no-store",
        )

    return response


@app.errorhandler(413)
def request_too_large(
    _error,
):
    if request.path.startswith(
        "/web_api/"
    ):
        return jsonify({
            "ok": False,
            "message": (
                "Request body is too large"
            ),
        }), 413

    return (
        "Request body is too large",
        413,
    )


@app.context_processor
def inject_login_context():
    return {
        "csrf_token": (
            get_csrf_token
        ),
        "current_user": getattr(
            g,
            "current_user",
            None,
        ),
    }


def _client_address() -> str:
    value = request.remote_addr

    if not value:
        return "unknown"

    return str(
        value
    )[:100]


def _redirect_no_store(
    location,
):
    response = redirect(
        location,
        code=303,
    )

    response.headers[
        "Cache-Control"
    ] = "no-store"

    return response


@app.route(
    "/login",
    methods=[
        "GET",
        "POST",
    ],
)
def login():
    if g.current_user is not None:
        return _redirect_no_store(
            url_for(
                "dashboard"
            )
        )

    error_message = ""

    next_path = request.args.get(
        "next",
        "",
    )

    missing_variables = (
        get_missing_login_environment()
    )

    if missing_variables:
        error_message = (
            "Login environment is "
            "not configured: "
            + ", ".join(
                missing_variables
            )
        )

    elif request.method == "POST":
        next_path = request.form.get(
            "next",
            "",
        )

        if not validate_csrf_token(
            request.form.get(
                "csrf_token"
            )
        ):
            logger.warning(
                (
                    "Login rejected because "
                    "the CSRF token was invalid: "
                    "client=%s"
                ),
                _client_address(),
            )

            error_message = (
                "Login page expired. "
                "Please try again."
            )

        else:
            username = request.form.get(
                "username",
                "",
            )

            password = request.form.get(
                "password",
                "",
            )

            if authenticate_login(
                username,
                password,
            ):
                try:
                    create_login_session()

                except RuntimeError:
                    logger.exception(
                        (
                            "Cannot create Web "
                            "login session"
                        )
                    )

                    error_message = (
                        "Login is temporarily "
                        "unavailable"
                    )

                else:
                    logger.info(
                        (
                            "Web login succeeded: "
                            "client=%s"
                        ),
                        _client_address(),
                    )

                    if is_safe_next_path(
                        next_path
                    ):
                        return _redirect_no_store(
                            next_path
                        )

                    return _redirect_no_store(
                        url_for(
                            "dashboard"
                        )
                    )

            else:
                logger.warning(
                    (
                        "Web login failed: "
                        "client=%s"
                    ),
                    _client_address(),
                )

                error_message = (
                    "Invalid username or password"
                )

    return render_template(
        "login.html",
        error_message=error_message,
        next_path=(
            next_path
            if is_safe_next_path(
                next_path
            )
            else ""
        ),
    )


@app.route(
    "/logout",
    methods=["POST"],
)
@login_required
def logout():
    if not validate_csrf_token(
        request.form.get(
            "csrf_token"
        )
    ):
        logger.warning(
            (
                "Logout rejected because "
                "the CSRF token was invalid: "
                "client=%s"
            ),
            _client_address(),
        )

        return (
            "Invalid request token",
            400,
        )

    username = (
        g.current_user.get(
            "username"
        )
        if g.current_user
        else ""
    )

    clear_login_session()

    logger.info(
        (
            "Web logout completed: "
            "username=%s, client=%s"
        ),
        username,
        _client_address(),
    )

    return _redirect_no_store(
        url_for(
            "login"
        )
    )


def _is_safe_api_path(
    api_path,
) -> bool:
    if not isinstance(
        api_path,
        str,
    ):
        return False

    if (
        not api_path
        or len(
            api_path
        ) > MAX_API_PATH_LENGTH
        or "\\" in api_path
        or "\x00" in api_path
        or "?" in api_path
        or "#" in api_path
    ):
        return False

    segments = api_path.split(
        "/"
    )

    if (
        len(
            segments
        ) < 2
        or segments[0] != "api"
    ):
        return False

    return all(
        bool(
            segment
        )
        and segment not in {
            ".",
            "..",
        }
        and _SAFE_API_SEGMENT.fullmatch(
            segment
        )
        is not None
        for segment in segments
    )


def _api_target_url(
    api_path,
) -> str:
    if not _is_safe_api_path(
        api_path
    ):
        raise ValueError(
            "Invalid API path"
        )

    return (
        f"{API_SERVER_URL.rstrip('/')}/"
        f"{api_path}"
    )


def _validate_response_size(
    response,
) -> None:
    raw_content_length = (
        response.headers.get(
            "Content-Length"
        )
    )

    if not raw_content_length:
        return

    try:
        content_length = int(
            raw_content_length
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return

    if content_length > MAX_PROXY_RESPONSE_BYTES:
        raise ProxyResponseTooLargeError(
            (
                "API response exceeds "
                "the allowed size"
            )
        )


def _read_limited_response(
    response,
) -> bytes:
    _validate_response_size(
        response
    )

    chunks = []
    total_size = 0

    for chunk in response.iter_content(
        chunk_size=(
            PROXY_READ_CHUNK_SIZE
        )
    ):
        if not chunk:
            continue

        total_size += len(
            chunk
        )

        if total_size > MAX_PROXY_RESPONSE_BYTES:
            raise ProxyResponseTooLargeError(
                (
                    "API response exceeds "
                    "the allowed size"
                )
            )

        chunks.append(
            chunk
        )

    return b"".join(
        chunks
    )


def _response_content_type(
    response,
) -> str:
    content_type = response.headers.get(
        "Content-Type",
        "application/json",
    )

    if (
        not isinstance(
            content_type,
            str,
        )
        or "\r" in content_type
        or "\n" in content_type
    ):
        return "application/octet-stream"

    return content_type[:200]


def get_api_json(
    api_path,
    params=None,
):
    target_url = _api_target_url(
        api_path.lstrip(
            "/"
        )
    )

    response = None

    try:
        response = requests.get(
            target_url,
            headers={
                "Authorization": (
                    f"Bearer {API_KEY}"
                ),
                "Accept": (
                    "application/json"
                ),
            },
            params=params,
            timeout=(
                DEFAULT_API_TIMEOUT
            ),
            stream=True,
        )

        response.raise_for_status()

        response_content = (
            _read_limited_response(
                response
            )
        )

        result = json.loads(
            response_content.decode(
                "utf-8"
            )
        )

        if not isinstance(
            result,
            dict,
        ):
            raise ValueError(
                (
                    "API response must be "
                    "a JSON object"
                )
            )

        return result

    finally:
        if response is not None:
            response.close()


def _latest_file_or_none(
    directory: Path,
):
    try:
        return get_latest_file(
            directory
        )

    except OSError as error:
        logger.warning(
            (
                "Cannot inspect latest image "
                "in %s: %s"
            ),
            directory,
            error,
        )

        return None

    except Exception:
        logger.exception(
            (
                "Unexpected error while "
                "loading latest image from %s"
            ),
            directory,
        )

        return None


def _validate_settings_bootstrap(
    settings_data,
):
    if not isinstance(
        settings_data,
        dict,
    ):
        raise ValueError(
            (
                "Settings response must "
                "be a JSON object"
            )
        )

    if settings_data.get(
        "ok"
    ) is False:
        raise ValueError(
            str(
                settings_data.get(
                    "message"
                )
                or "Settings API failed"
            )
        )

    calibration = settings_data.get(
        "calibration"
    )

    if (
        calibration is not None
        and not isinstance(
            calibration,
            dict,
        )
    ):
        raise ValueError(
            (
                "calibration must be "
                "an object or null"
            )
        )

    user_tags = settings_data.get(
        "user_tags",
        [],
    )

    if not isinstance(
        user_tags,
        list,
    ):
        raise ValueError(
            "user_tags must be a list"
        )

    return (
        calibration,
        user_tags,
    )


def _save_settings_cache(
    calibration,
    user_tags,
) -> None:
    global _settings_cache

    with _settings_cache_lock:
        _settings_cache = (
            copy.deepcopy(
                calibration
            ),
            copy.deepcopy(
                user_tags
            ),
        )


def _load_settings_cache():
    with _settings_cache_lock:
        if _settings_cache is None:
            return (
                None,
                [],
                False,
            )

        calibration, user_tags = (
            _settings_cache
        )

        return (
            copy.deepcopy(
                calibration
            ),
            copy.deepcopy(
                user_tags
            ),
            True,
        )


@app.route("/")
@login_required
def home():
    return redirect(
        url_for(
            "dashboard"
        )
    )


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html"
    )


@app.route("/settings")
@login_required
def settings():
    latest_image = (
        _latest_file_or_none(
            RAW_IMAGES_DIR
        )
    )

    using_cached_settings = False

    try:
        settings_data = get_api_json(
            "/api/settings/bootstrap"
        )

        (
            calibration,
            user_tags,
        ) = _validate_settings_bootstrap(
            settings_data
        )

        _save_settings_cache(
            calibration,
            user_tags,
        )

        logger.debug(
            (
                "Settings data loaded "
                "successfully"
            )
        )

    except requests.Timeout:
        logger.warning(
            "Settings API timed out"
        )

        (
            calibration,
            user_tags,
            using_cached_settings,
        ) = _load_settings_cache()

    except requests.RequestException as error:
        logger.warning(
            (
                "Cannot load Settings API: "
                "%s"
            ),
            error,
        )

        (
            calibration,
            user_tags,
            using_cached_settings,
        ) = _load_settings_cache()

    except (
        TypeError,
        ValueError,
        UnicodeError,
        ProxyResponseTooLargeError,
    ) as error:
        logger.warning(
            (
                "Invalid Settings API "
                "response: %s"
            ),
            error,
        )

        (
            calibration,
            user_tags,
            using_cached_settings,
        ) = _load_settings_cache()

    except Exception:
        logger.exception(
            (
                "Unexpected error while "
                "loading Settings data"
            )
        )

        (
            calibration,
            user_tags,
            using_cached_settings,
        ) = _load_settings_cache()

    if calibration is None:
        latest_calibrated_image = None

    else:
        latest_calibrated_image = (
            _latest_file_or_none(
                CALIBRATED_IMAGES_DIR
            )
        )

    return render_template(
        "settings.html",
        latest_image=latest_image,
        latest_calibrated_image=(
            latest_calibrated_image
        ),
        roi_list=user_tags,
        using_cached_settings=(
            using_cached_settings
        ),
    )


@app.route("/history")
@login_required
def history():
    return render_template(
        "history.html"
    )


@app.route("/logs")
@login_required
def logs_page():
    return render_template(
        "logs.html"
    )


@app.route("/live")
@login_required
def live():
    return render_template(
        "live.html"
    )


@app.route(
    "/raw_images/<path:filename>"
)
@login_required
def raw_images(
    filename,
):
    return send_from_directory(
        RAW_IMAGES_DIR,
        filename,
        conditional=True,
        max_age=0,
    )


@app.route(
    "/calibrated_images/<path:filename>"
)
@login_required
def calibrated_images(
    filename,
):
    return send_from_directory(
        CALIBRATED_IMAGES_DIR,
        filename,
        conditional=True,
        max_age=0,
    )


@app.route("/video_feed")
@login_required
def video_feed():
    return Response(
        generate_camera_frames(),
        mimetype=(
            "multipart/x-mixed-replace; "
            "boundary=frame"
        ),
        headers={
            "Cache-Control": (
                "no-store, no-cache, "
                "must-revalidate, max-age=0"
            ),
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _log_live_warning(
    warning_key: str,
    message: str,
    *args,
) -> None:
    current_time = (
        monotonic()
    )

    with _live_warning_lock:
        previous_time = (
            _live_warning_times.get(
                warning_key,
                0.0,
            )
        )

        if (
            previous_time > 0
            and (
                current_time
                - previous_time
            )
            < LIVE_WARNING_INTERVAL_SECONDS
        ):
            return

        _live_warning_times[
            warning_key
        ] = current_time

    logger.warning(
        message,
        *args,
    )


def _release_capture(
    cap,
) -> None:
    if cap is None:
        return

    try:
        cap.release()

    except Exception:
        logger.exception(
            (
                "Failed to release live "
                "camera capture"
            )
        )


def _capture_is_opened(
    cap,
) -> bool:
    if cap is None:
        return False

    try:
        return bool(
            cap.isOpened()
        )

    except Exception:
        return False


def _create_live_capture(
    rtsp_url,
):
    parameters = []

    if hasattr(
        cv2,
        "CAP_PROP_OPEN_TIMEOUT_MSEC",
    ):
        parameters.extend([
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            LIVE_OPEN_TIMEOUT_MSEC,
        ])

    if hasattr(
        cv2,
        "CAP_PROP_READ_TIMEOUT_MSEC",
    ):
        parameters.extend([
            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            LIVE_READ_TIMEOUT_MSEC,
        ])

    cap = None

    if parameters:
        try:
            cap = cv2.VideoCapture(
                rtsp_url,
                cv2.CAP_FFMPEG,
                parameters,
            )

        except (
            TypeError,
            cv2.error,
        ):
            cap = None

    if cap is None:
        cap = cv2.VideoCapture(
            rtsp_url,
            cv2.CAP_FFMPEG,
        )

        try:
            if hasattr(
                cv2,
                "CAP_PROP_OPEN_TIMEOUT_MSEC",
            ):
                cap.set(
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    LIVE_OPEN_TIMEOUT_MSEC,
                )

            if hasattr(
                cv2,
                "CAP_PROP_READ_TIMEOUT_MSEC",
            ):
                cap.set(
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    LIVE_READ_TIMEOUT_MSEC,
                )

        except Exception:
            pass

    try:
        cap.set(
            cv2.CAP_PROP_BUFFERSIZE,
            1,
        )

    except Exception:
        pass

    return cap


def _valid_frame(
    frame,
) -> bool:
    return (
        isinstance(
            frame,
            np.ndarray,
        )
        and frame.size > 0
        and frame.ndim in {
            2,
            3,
        }
        and frame.shape[0] > 0
        and frame.shape[1] > 0
    )


def _create_placeholder_frame(
    message: str,
):
    frame = np.full(
        (
            LIVE_PLACEHOLDER_HEIGHT,
            LIVE_PLACEHOLDER_WIDTH,
            3,
        ),
        32,
        dtype=np.uint8,
    )

    cv2.putText(
        frame,
        "OCR Monitoring",
        (
            42,
            90,
        ),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (
            230,
            230,
            230,
        ),
        2,
        cv2.LINE_AA,
    )

    cv2.putText(
        frame,
        str(
            message
        ),
        (
            42,
            170,
        ),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (
            200,
            200,
            200,
        ),
        2,
        cv2.LINE_AA,
    )

    cv2.putText(
        frame,
        (
            "The system will retry "
            "automatically."
        ),
        (
            42,
            220,
        ),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (
            160,
            160,
            160,
        ),
        1,
        cv2.LINE_AA,
    )

    return frame


def _encode_frame(
    frame,
) -> bytes | None:
    if not _valid_frame(
        frame
    ):
        return None

    try:
        encoded, buffer = (
            cv2.imencode(
                ".jpg",
                frame,
            )
        )

    except cv2.error as error:
        _log_live_warning(
            "encode_exception",
            (
                "OpenCV failed to encode "
                "live frame: %s"
            ),
            error,
        )

        return None

    if not encoded:
        _log_live_warning(
            "encode_failed",
            (
                "Cannot encode live "
                "camera frame"
            ),
        )

        return None

    return buffer.tobytes()


def _build_mjpeg_chunk(
    frame,
) -> bytes | None:
    frame_bytes = (
        _encode_frame(
            frame
        )
    )

    if frame_bytes is None:
        return None

    return (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Cache-Control: no-cache\r\n\r\n"
        + frame_bytes
        + b"\r\n"
    )


def _placeholder_chunk(
    message: str,
) -> bytes | None:
    return _build_mjpeg_chunk(
        _create_placeholder_frame(
            message
        )
    )


def generate_camera_frames():
    cap = None
    read_failures = 0
    current_state = None

    try:
        while True:
            if cap is None:
                try:
                    camera = (
                        reload_camera_config()
                    )

                except CameraNotConfiguredError:
                    if (
                        current_state
                        != "not_configured"
                    ):
                        logger.info(
                            (
                                "Live camera is "
                                "waiting for "
                                "configuration"
                            )
                        )

                        current_state = (
                            "not_configured"
                        )

                    chunk = _placeholder_chunk(
                        (
                            "Camera is not "
                            "configured."
                        )
                    )

                    if chunk is not None:
                        yield chunk

                    time.sleep(
                        LIVE_RETRY_SECONDS
                    )

                    continue

                except CameraConfigError as error:
                    _log_live_warning(
                        "config_unavailable",
                        (
                            "Live camera "
                            "configuration is "
                            "unavailable: %s"
                        ),
                        error,
                    )

                    current_state = (
                        "config_unavailable"
                    )

                    chunk = _placeholder_chunk(
                        (
                            "Camera configuration "
                            "is unavailable."
                        )
                    )

                    if chunk is not None:
                        yield chunk

                    time.sleep(
                        LIVE_RETRY_SECONDS
                    )

                    continue

                try:
                    cap = _create_live_capture(
                        camera.rtsp_url
                    )

                except Exception as error:
                    cap = None

                    _log_live_warning(
                        "capture_open_exception",
                        (
                            "Cannot create live "
                            "camera capture: %s"
                        ),
                        error,
                    )

                if not _capture_is_opened(
                    cap
                ):
                    _release_capture(
                        cap
                    )

                    cap = None
                    read_failures = 0
                    current_state = (
                        "connection_failed"
                    )

                    _log_live_warning(
                        "connection_failed",
                        (
                            "Live camera "
                            "connection failed"
                        ),
                    )

                    chunk = _placeholder_chunk(
                        (
                            "Cannot connect "
                            "to camera."
                        )
                    )

                    if chunk is not None:
                        yield chunk

                    time.sleep(
                        LIVE_RETRY_SECONDS
                    )

                    continue

                logger.info(
                    (
                        "Live camera stream "
                        "connected: camera=%s"
                    ),
                    (
                        camera.camera_name
                        or "configured camera"
                    ),
                )

                current_state = "connected"
                read_failures = 0

            try:
                success, frame = cap.read()

            except Exception as error:
                success = False
                frame = None

                _log_live_warning(
                    "capture_read_exception",
                    (
                        "Live camera read "
                        "failed: %s"
                    ),
                    error,
                )

            if (
                not success
                or not _valid_frame(
                    frame
                )
            ):
                read_failures += 1

                if (
                    read_failures
                    < LIVE_READ_FAILURE_LIMIT
                ):
                    time.sleep(
                        LIVE_READ_RETRY_SECONDS
                    )

                    continue

                _log_live_warning(
                    "camera_stopped",
                    (
                        "Live camera stopped "
                        "responding; reconnecting"
                    ),
                )

                _release_capture(
                    cap
                )

                cap = None
                read_failures = 0
                current_state = (
                    "camera_stopped"
                )

                chunk = _placeholder_chunk(
                    (
                        "Camera connection "
                        "was interrupted."
                    )
                )

                if chunk is not None:
                    yield chunk

                time.sleep(
                    LIVE_RETRY_SECONDS
                )

                continue

            read_failures = 0

            chunk = _build_mjpeg_chunk(
                frame
            )

            if chunk is not None:
                yield chunk

    except GeneratorExit:
        logger.debug(
            (
                "Live camera viewer "
                "disconnected"
            )
        )

    except (
        BrokenPipeError,
        ConnectionResetError,
    ):
        logger.debug(
            (
                "Live camera viewer "
                "connection closed"
            )
        )

    except Exception:
        logger.exception(
            (
                "Unexpected live camera "
                "stream error"
            )
        )

    finally:
        _release_capture(
            cap
        )


def _read_proxy_json_payload():
    if not request.data:
        return {}

    if not request.is_json:
        raise ValueError(
            (
                "Request body must use "
                "application/json"
            )
        )

    try:
        payload = request.get_json(
            silent=False
        )

    except BadRequest as error:
        raise ValueError(
            "Request body contains invalid JSON"
        ) from error

    if payload is None:
        return {}

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            (
                "Request JSON must be "
                "an object"
            )
        )

    return payload


@app.route(
    "/web_api/<path:api_path>",
    methods=[
        "GET",
        "POST",
    ],
)
@login_required_json
def web_api_proxy(
    api_path,
):
    is_log_viewer_request = (
        api_path
        == "api/system/logs"
    )

    if not _is_safe_api_path(
        api_path
    ):
        logger.warning(
            (
                "Invalid Web proxy API "
                "path: %s"
            ),
            api_path[:MAX_API_PATH_LENGTH],
        )

        return jsonify({
            "ok": False,
            "message": (
                "Invalid API path"
            ),
        }), 400

    target_url = _api_target_url(
        api_path
    )

    authorization_headers = {
        "Authorization": (
            f"Bearer {API_KEY}"
        ),
        "Accept": "application/json",
    }

    proxy_timeout = (
        DEFAULT_API_TIMEOUT
    )

    if api_path in {
        "api/capture_image",
        "api/camera/test",
    }:
        proxy_timeout = (
            LONG_API_TIMEOUT
        )

    response = None

    try:
        if request.method == "GET":
            response = requests.get(
                target_url,
                headers=(
                    authorization_headers
                ),
                params=request.args,
                timeout=proxy_timeout,
                stream=True,
            )

        else:
            try:
                payload = (
                    _read_proxy_json_payload()
                )

            except ValueError as error:
                return jsonify({
                    "ok": False,
                    "message": str(
                        error
                    ),
                }), 400

            response = requests.post(
                target_url,
                headers={
                    **authorization_headers,
                    "Content-Type": (
                        "application/json"
                    ),
                },
                json=payload,
                timeout=proxy_timeout,
                stream=True,
            )

        status_code = (
            response.status_code
        )

        response_content = (
            _read_limited_response(
                response
            )
        )

        content_type = (
            _response_content_type(
                response
            )
        )

        if not is_log_viewer_request:
            logger.debug(
                (
                    "Web proxy response: "
                    "method=%s, path=%s, "
                    "status=%s"
                ),
                request.method,
                api_path,
                status_code,
            )

        if status_code >= 500:
            logger.warning(
                (
                    "API proxy returned "
                    "server error: method=%s, "
                    "path=%s, status=%s"
                ),
                request.method,
                api_path,
                status_code,
            )

        return (
            response_content,
            status_code,
            {
                "Content-Type": (
                    content_type
                ),
                "Cache-Control": (
                    "no-store"
                ),
                "X-Content-Type-Options": (
                    "nosniff"
                ),
            },
        )

    except ProxyResponseTooLargeError:
        logger.warning(
            (
                "API proxy response was too "
                "large: method=%s, path=%s"
            ),
            request.method,
            api_path,
        )

        return jsonify({
            "ok": False,
            "message": (
                "API response is too large"
            ),
        }), 502

    except requests.Timeout:
        logger.warning(
            (
                "API proxy timeout: "
                "method=%s, path=%s"
            ),
            request.method,
            api_path,
        )

        return jsonify({
            "ok": False,
            "message": (
                "API server response timeout"
            ),
        }), 504

    except requests.RequestException as error:
        logger.warning(
            (
                "Cannot connect to API server: "
                "method=%s, path=%s, error=%s"
            ),
            request.method,
            api_path,
            error,
        )

        return jsonify({
            "ok": False,
            "message": (
                "Cannot connect to API server"
            ),
        }), 502

    except Exception:
        logger.exception(
            (
                "Unexpected Web API proxy "
                "error: method=%s, path=%s"
            ),
            request.method,
            api_path,
        )

        return jsonify({
            "ok": False,
            "message": (
                "Web API proxy failed"
            ),
        }), 500

    finally:
        if response is not None:
            response.close()


if __name__ == "__main__":
    logger.info(
        "Web application starting"
    )

    app.run(
        host=os.getenv(
            "WEB_HOST",
            "0.0.0.0",
        ).strip()
        or "0.0.0.0",
        port=_environment_port(
            "WEB_PORT",
            5000,
        ),
        debug=False,
        use_reloader=False,
        threaded=True,
    )