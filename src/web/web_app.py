import time

import cv2
import requests
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
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


logger = create_logger(
    "web.app"
)


app = Flask(__name__)


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
def home():
    return redirect(
        "/dashboard"
    )


@app.route("/dashboard")
def dashboard():
    return render_template(
        "dashboard.html"
    )


@app.route("/settings")
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
def history():
    return render_template(
        "history.html"
    )


@app.route("/live")
def live():
    return render_template(
        "live.html"
    )


@app.route(
    "/raw_images/<path:filename>"
)
def raw_images(filename):
    return send_from_directory(
        RAW_IMAGES_DIR,
        filename,
    )


@app.route(
    "/calibrated_images/<path:filename>"
)
def calibrated_images(filename):
    return send_from_directory(
        CALIBRATED_IMAGES_DIR,
        filename,
    )


@app.route("/video_feed")
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
def web_api_proxy(api_path):
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