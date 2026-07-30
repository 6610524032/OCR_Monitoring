import os
import time
from datetime import timedelta

import cv2
import requests
from flask import (
    Flask,
    g,
    Response,
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


app = Flask(__name__)

app.config.update(
    SECRET_KEY=get_session_secret(),
    PERMANENT_SESSION_LIFETIME=(
        timedelta(hours=8)
    ),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        os.getenv(
            "WEB_SESSION_COOKIE_SECURE",
            "false",
        ).strip().lower()
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
            "Web login environment is incomplete. "
            "Missing: %s"
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
        "csrf_token": get_csrf_token,
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
            "Login environment is not configured: "
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


def get_api_json(
    api_path,
    params=None,
):
    target_url = (
        f"{API_SERVER_URL.rstrip('/')}/"
        f"{api_path.lstrip('/')}"
    )

    response = requests.get(
        target_url,
        headers={
            "Authorization": (
                f"Bearer {API_KEY}"
            )
        },
        params=params,
        timeout=10,
    )

    response.raise_for_status()

    return response.json()


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
    latest_image = get_latest_file(
        RAW_IMAGES_DIR
    )

    try:
        settings_data = get_api_json(
            "/api/settings/bootstrap"
        )

        calibration = settings_data.get(
            "calibration"
        )

        user_tags = settings_data.get(
            "user_tags",
            [],
        )

        logger.info(
            "Settings data loaded successfully"
        )

    except requests.RequestException:
        logger.exception(
            "Cannot load settings API"
        )

        calibration = None
        user_tags = []

    except ValueError:
        logger.exception(
            "Invalid settings API response"
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
def raw_images(filename):
    return send_from_directory(
        RAW_IMAGES_DIR,
        filename,
    )


@app.route(
    "/calibrated_images/<path:filename>"
)
@login_required
def calibrated_images(filename):
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
    )


def generate_camera_frames():
    while True:
        try:
            camera = reload_camera_config()

        except CameraConfigError:
            logger.exception(
                "Failed to load live camera configuration"
            )

            time.sleep(2)
            continue

        cap = cv2.VideoCapture(
            camera.rtsp_url,
            cv2.CAP_FFMPEG,
        )

        if not cap.isOpened():
            logger.warning(
                "Cannot open RTSP stream"
            )

            cap.release()
            time.sleep(2)
            continue

        logger.debug(
            "Live camera stream connected"
        )

        try:
            while True:
                success, frame = cap.read()

                if not success:
                    logger.warning(
                        "Cannot read RTSP frame"
                    )
                    break

                encoded, buffer = cv2.imencode(
                    ".jpg",
                    frame,
                )

                if not encoded:
                    continue

                frame_bytes = buffer.tobytes()

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame_bytes
                    + b"\r\n"
                )

        except Exception:
            logger.exception(
                "Unexpected live camera stream error"
            )

        finally:
            cap.release()

        time.sleep(2)


@app.route(
    "/web_api/<path:api_path>",
    methods=["GET", "POST"],
)
@login_required_json
def web_api_proxy(api_path):
    is_log_viewer_request = (
        api_path == "api/system/logs"
    )

    if not is_log_viewer_request:
        logger.info(
            "Proxy request: %s %s",
            request.method,
            api_path,
        )

    if not api_path.startswith("api/"):
        logger.warning(
            "Invalid web proxy API path: %s",
            api_path,
        )

        return jsonify({
            "ok": False,
            "message": "Invalid API path",
        }), 400

    target_url = (
        f"{API_SERVER_URL.rstrip('/')}/"
        f"{api_path}"
    )

    authorization_headers = {
        "Authorization": (
            f"Bearer {API_KEY}"
        )
    }

    proxy_timeout = 10

    if api_path in {
        "api/capture_image",
        "api/camera/test",
    }:
        proxy_timeout = 60

    try:
        if request.method == "GET":
            response = requests.get(
                target_url,
                headers=authorization_headers,
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

        if not is_log_viewer_request:
            logger.info(
                "Proxy response %s -> HTTP %s",
                api_path,
                response.status_code,
            )

        if response.status_code >= 500:
            logger.warning(
                "API proxy returned server error "
                "(method=%s, path=%s, status=%s)",
                request.method,
                api_path,
                response.status_code,
            )

        return (
            response.content,
            response.status_code,
            {
                "Content-Type": (
                    response.headers.get(
                        "Content-Type",
                        "application/json",
                    )
                )
            },
        )

    except requests.Timeout:
        logger.warning(
            "API proxy timeout "
            "(method=%s, path=%s)",
            request.method,
            api_path,
        )

        return jsonify({
            "ok": False,
            "message": (
                "API server response timeout"
            ),
        }), 504

    except requests.RequestException:
        logger.exception(
            "Cannot connect to API server "
            "(method=%s, path=%s)",
            request.method,
            api_path,
        )

        return jsonify({
            "ok": False,
            "message": (
                "Cannot connect to API server"
            ),
        }), 502


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