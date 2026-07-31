import copy
import json
import os
import time
from datetime import timedelta
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
    session,
    url_for,
)

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

LIVE_RETRY_SECONDS = 5
LIVE_WARNING_INTERVAL_SECONDS = 60

LIVE_PLACEHOLDER_WIDTH = 960
LIVE_PLACEHOLDER_HEIGHT = 540

WEB_GET_CACHE_MAX_ITEMS = 256
WEB_GET_CACHE_MAX_AGE_SECONDS = 3600


_live_warning_lock = Lock()
_live_warning_times: dict[
    str,
    float,
] = {}

_web_get_cache_lock = Lock()
_web_get_cache: dict[
    tuple[str, str, str],
    tuple[float, object],
] = {}


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
        os.getenv(
            "WEB_SESSION_COOKIE_SECURE",
            "false",
        )
        .strip()
        .lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
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


@app.route(
    "/login",
    methods=[
        "GET",
        "POST",
    ],
)
def login():
    if g.current_user is not None:
        return redirect(
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
                    "CSRF token was invalid"
                )
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
                create_login_session()

                logger.info(
                    (
                        "Web login succeeded: "
                        "username=%s"
                    ),
                    username,
                )

                if is_safe_next_path(
                    next_path
                ):
                    return redirect(
                        next_path
                    )

                return redirect(
                    url_for(
                        "dashboard"
                    )
                )

            logger.warning(
                (
                    "Web login failed: "
                    "username=%s"
                ),
                username,
            )

            error_message = (
                "Invalid username or password"
            )

    return render_template(
        "login.html",
        error_message=error_message,
        next_path=next_path,
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

    session.clear()

    logger.info(
        (
            "Web logout completed: "
            "username=%s"
        ),
        username,
    )

    return redirect(
        url_for(
            "login"
        )
    )



def _normalize_cache_params(
    params,
) -> str:
    if params is None:
        return ""

    if hasattr(
        params,
        "to_dict",
    ):
        try:
            params = params.to_dict(
                flat=False
            )

        except TypeError:
            params = params.to_dict()

    try:
        return json.dumps(
            params,
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
        return repr(
            params
        )


def _web_cache_key(
    namespace: str,
    api_path: str,
    params,
) -> tuple[str, str, str]:
    return (
        namespace,
        str(
            api_path
        ),
        _normalize_cache_params(
            params
        ),
    )


def _store_web_get_cache(
    namespace: str,
    api_path: str,
    params,
    value,
) -> None:
    key = _web_cache_key(
        namespace,
        api_path,
        params,
    )

    stored_at = monotonic()

    with _web_get_cache_lock:
        if (
            key not in _web_get_cache
            and len(
                _web_get_cache
            ) >= WEB_GET_CACHE_MAX_ITEMS
        ):
            oldest_key = min(
                _web_get_cache,
                key=lambda current_key: (
                    _web_get_cache[
                        current_key
                    ][0]
                ),
            )

            _web_get_cache.pop(
                oldest_key,
                None,
            )

        _web_get_cache[
            key
        ] = (
            stored_at,
            copy.deepcopy(
                value
            ),
        )


def _load_web_get_cache(
    namespace: str,
    api_path: str,
    params,
):
    key = _web_cache_key(
        namespace,
        api_path,
        params,
    )

    current_time = monotonic()

    with _web_get_cache_lock:
        cached_item = (
            _web_get_cache.get(
                key
            )
        )

        if cached_item is None:
            return (
                None,
                None,
            )

        stored_at, value = (
            cached_item
        )

        age_seconds = max(
            0.0,
            current_time - stored_at,
        )

        if (
            age_seconds
            > WEB_GET_CACHE_MAX_AGE_SECONDS
        ):
            _web_get_cache.pop(
                key,
                None,
            )

            return (
                None,
                None,
            )

        return (
            copy.deepcopy(
                value
            ),
            age_seconds,
        )


def _load_cached_json_response(
    api_path,
    params,
    reason: str,
):
    cached_result, age_seconds = (
        _load_web_get_cache(
            "json",
            api_path,
            params,
        )
    )

    if cached_result is None:
        return None

    logger.warning(
        (
            "Using cached Web API JSON: "
            "path=%s, age_seconds=%.1f, "
            "reason=%s"
        ),
        api_path,
        age_seconds,
        reason,
    )

    return cached_result


def _load_cached_proxy_response(
    api_path,
    params,
    reason: str,
):
    cached_result, age_seconds = (
        _load_web_get_cache(
            "proxy",
            api_path,
            params,
        )
    )

    if cached_result is None:
        return None

    response_content, status_code, content_type = (
        cached_result
    )

    logger.warning(
        (
            "Using cached Web API proxy "
            "response: path=%s, "
            "age_seconds=%.1f, reason=%s"
        ),
        api_path,
        age_seconds,
        reason,
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
            "X-Data-Source": (
                "fallback-cache"
            ),
            "X-Cache-Age-Seconds": (
                f"{age_seconds:.1f}"
            ),
        },
    )

def get_api_json(
    api_path,
    params=None,
):
    target_url = (
        f"{API_SERVER_URL.rstrip('/')}/"
        f"{api_path.lstrip('/')}"
    )

    response = None

    try:
        response = requests.get(
            target_url,
            headers={
                "Authorization": (
                    f"Bearer {API_KEY}"
                ),
            },
            params=params,
            timeout=(
                DEFAULT_API_TIMEOUT
            ),
        )

        response.raise_for_status()

        result = response.json()

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

        if result.get(
            "ok"
        ) is not False:
            _store_web_get_cache(
                "json",
                api_path,
                params,
                result,
            )

        return result

    except requests.HTTPError:
        status_code = (
            response.status_code
            if response is not None
            else None
        )

        if (
            status_code is not None
            and status_code >= 500
        ):
            cached_result = (
                _load_cached_json_response(
                    api_path,
                    params,
                    f"HTTP {status_code}",
                )
            )

            if cached_result is not None:
                return cached_result

        raise

    except requests.Timeout:
        cached_result = (
            _load_cached_json_response(
                api_path,
                params,
                "timeout",
            )
        )

        if cached_result is not None:
            return cached_result

        raise

    except requests.RequestException:
        cached_result = (
            _load_cached_json_response(
                api_path,
                params,
                "connection error",
            )
        )

        if cached_result is not None:
            return cached_result

        raise

    except (
        TypeError,
        ValueError,
    ):
        cached_result = (
            _load_cached_json_response(
                api_path,
                params,
                "invalid response",
            )
        )

        if cached_result is not None:
            return cached_result

        raise

    finally:
        if response is not None:
            response.close()


@app.route("/")
@login_required
def home():
    return redirect(
        "/dashboard"
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
        get_latest_file(
            RAW_IMAGES_DIR
        )
    )

    try:
        settings_data = get_api_json(
            "/api/settings/bootstrap"
        )

        calibration = (
            settings_data.get(
                "calibration"
            )
        )

        user_tags = (
            settings_data.get(
                "user_tags",
                [],
            )
        )

        if not isinstance(
            user_tags,
            list,
        ):
            raise ValueError(
                (
                    "user_tags must "
                    "be a list"
                )
            )

        logger.debug(
            (
                "Settings data loaded "
                "successfully"
            )
        )

    except requests.Timeout as error:
        logger.warning(
            "Settings API timeout: %s",
            error,
        )

        calibration = None
        user_tags = []

    except requests.RequestException as error:
        logger.warning(
            (
                "Cannot load settings "
                "API: %s"
            ),
            error,
        )

        calibration = None
        user_tags = []

    except (
        TypeError,
        ValueError,
    ) as error:
        logger.warning(
            (
                "Invalid settings API "
                "response: %s"
            ),
            error,
        )

        calibration = None
        user_tags = []

    if calibration is None:
        latest_calibrated_image = None

    else:
        latest_calibrated_image = (
            get_latest_file(
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
    if frame is None:
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
    current_state = None

    try:
        while True:
            if cap is None:
                try:
                    camera = (
                        reload_camera_config()
                    )

                except (
                    CameraNotConfiguredError
                ):
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

                    chunk = (
                        _placeholder_chunk(
                            (
                                "Camera is not "
                                "configured."
                            )
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

                    chunk = (
                        _placeholder_chunk(
                            (
                                "Camera configuration "
                                "is unavailable."
                            )
                        )
                    )

                    if chunk is not None:
                        yield chunk

                    time.sleep(
                        LIVE_RETRY_SECONDS
                    )

                    continue

                try:
                    cap = cv2.VideoCapture(
                        camera.rtsp_url,
                        cv2.CAP_FFMPEG,
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

                if (
                    cap is None
                    or not cap.isOpened()
                ):
                    _release_capture(
                        cap
                    )

                    cap = None

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

                    chunk = (
                        _placeholder_chunk(
                            (
                                "Cannot connect "
                                "to camera."
                            )
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
                    camera.camera_name,
                )

                current_state = (
                    "connected"
                )

            try:
                success, frame = (
                    cap.read()
                )

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
                or frame is None
            ):
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

                current_state = (
                    "camera_stopped"
                )

                chunk = (
                    _placeholder_chunk(
                        (
                            "Camera connection "
                            "was interrupted."
                        )
                    )
                )

                if chunk is not None:
                    yield chunk

                time.sleep(
                    LIVE_RETRY_SECONDS
                )

                continue

            chunk = (
                _build_mjpeg_chunk(
                    frame
                )
            )

            if chunk is not None:
                yield chunk

    except GeneratorExit:
        logger.info(
            (
                "Live camera viewer "
                "disconnected"
            )
        )

    except (
        BrokenPipeError,
        ConnectionResetError,
    ):
        logger.info(
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

    if not is_log_viewer_request:
        logger.info(
            "Proxy request: %s %s",
            request.method,
            api_path,
        )

    if not api_path.startswith(
        "api/"
    ):
        logger.warning(
            (
                "Invalid web proxy "
                "API path: %s"
            ),
            api_path,
        )

        return jsonify({
            "ok": False,
            "message": (
                "Invalid API path"
            ),
        }), 400

    target_url = (
        f"{API_SERVER_URL.rstrip('/')}/"
        f"{api_path}"
    )

    authorization_headers = {
        "Authorization": (
            f"Bearer {API_KEY}"
        ),
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
            )

        else:
            response = requests.post(
                target_url,
                headers={
                    **authorization_headers,
                    "Content-Type": (
                        "application/json"
                    ),
                },
                json=(
                    request.get_json(
                        silent=True
                    )
                    or {}
                ),
                timeout=proxy_timeout,
            )

        status_code = (
            response.status_code
        )

        response_content = (
            response.content
        )

        content_type = (
            response.headers.get(
                "Content-Type",
                "application/json",
            )
        )

        if not is_log_viewer_request:
            logger.info(
                (
                    "Proxy response %s "
                    "-> HTTP %s"
                ),
                api_path,
                status_code,
            )

        if (
            request.method == "GET"
            and not is_log_viewer_request
            and 200 <= status_code < 300
        ):
            _store_web_get_cache(
                "proxy",
                api_path,
                request.args,
                (
                    response_content,
                    status_code,
                    content_type,
                ),
            )

        if status_code >= 500:
            logger.warning(
                (
                    "API proxy returned "
                    "server error "
                    "(method=%s, path=%s, "
                    "status=%s)"
                ),
                request.method,
                api_path,
                status_code,
            )

            if (
                request.method == "GET"
                and not is_log_viewer_request
            ):
                cached_response = (
                    _load_cached_proxy_response(
                        api_path,
                        request.args,
                        f"HTTP {status_code}",
                    )
                )

                if cached_response is not None:
                    return cached_response

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
                "X-Data-Source": (
                    "live-api"
                ),
            },
        )

    except requests.Timeout:
        if (
            request.method == "GET"
            and not is_log_viewer_request
        ):
            cached_response = (
                _load_cached_proxy_response(
                    api_path,
                    request.args,
                    "timeout",
                )
            )

            if cached_response is not None:
                return cached_response

        logger.warning(
            (
                "API proxy timeout "
                "(method=%s, path=%s)"
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
        if (
            request.method == "GET"
            and not is_log_viewer_request
        ):
            cached_response = (
                _load_cached_proxy_response(
                    api_path,
                    request.args,
                    "connection error",
                )
            )

            if cached_response is not None:
                return cached_response

        logger.warning(
            (
                "Cannot connect to API "
                "server (method=%s, "
                "path=%s): %s"
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

    finally:
        if response is not None:
            response.close()


if __name__ == "__main__":
    logger.info(
        "Web application starting"
    )

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
    )