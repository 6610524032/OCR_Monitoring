import time
import cv2
import requests
from flask import Flask, Response, redirect, render_template, send_from_directory, jsonify, request

from app.processing.calibration import get_latest_file
from app.server.config import (
    API_KEY,
    API_SERVER_URL,
    CALIBRATED_IMAGES_DIR,
    RAW_IMAGES_DIR
)
from app.server.camera_client import (
    CameraConfigError,
    reload_camera_config
)

app = Flask(__name__)


def get_api_json(api_path, params=None):
    target_url = (
        f"{API_SERVER_URL.rstrip('/')}/"
        f"{api_path.lstrip('/')}"
    )

    response = requests.get(
        target_url,
        headers={
            "Authorization": f"Bearer {API_KEY}"
        },
        params=params,
        timeout=10
    )

    response.raise_for_status()

    return response.json()


@app.route("/")
def home():
    return redirect("/dashboard")


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/settings")
def settings():
    latest_image = get_latest_file(RAW_IMAGES_DIR)

    try:
        settings_data = get_api_json(
            "/api/settings/bootstrap"
        )

        calibration = settings_data.get("calibration")
        user_tags = settings_data.get("user_tags", [])

    except requests.RequestException as error:
        print(f"Cannot load settings API: {error}")

        calibration = None
        user_tags = []

    except ValueError as error:
        print(f"Invalid settings API response: {error}")

        calibration = None
        user_tags = []

    if calibration is None:
        latest_calibrated_image = None
    else:
        latest_calibrated_image = get_latest_file(
            CALIBRATED_IMAGES_DIR
        )

    return render_template(
        "settings.html",
        latest_image=latest_image,
        latest_calibrated_image=latest_calibrated_image,
        roi_list=user_tags
    )


@app.route("/history")
def history():
    return render_template("history.html")


@app.route("/live")
def live():
    return render_template("live.html")


@app.route("/raw_images/<path:filename>")
def raw_images(filename):
    return send_from_directory(RAW_IMAGES_DIR, filename)


@app.route("/calibrated_images/<path:filename>")
def calibrated_images(filename):
    return send_from_directory(CALIBRATED_IMAGES_DIR, filename)


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_camera_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


def generate_camera_frames():

    while True:

        try:
            camera = reload_camera_config()

        except CameraConfigError as error:
            print(
                "[LIVE CAMERA CONFIG ERROR]",
                str(error)
            )

            time.sleep(2)
            continue

        cap = cv2.VideoCapture(
            camera.rtsp_url,
            cv2.CAP_FFMPEG
        )

        if not cap.isOpened():
            print(
                "[LIVE CAMERA ERROR]",
                "Cannot open RTSP stream"
            )

            cap.release()

            time.sleep(2)
            continue

        try:

            while True:

                success, frame = cap.read()

                if not success:

                    print(
                        "[LIVE CAMERA ERROR]",
                        "Cannot read RTSP frame"
                    )

                    break

                encoded, buffer = cv2.imencode(
                    ".jpg",
                    frame
                )

                if not encoded:
                    continue

                frame_bytes = buffer.tobytes()

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame_bytes +
                    b"\r\n"
                )

        finally:

            cap.release()

        print(
            "[LIVE CAMERA]",
            "Reconnect in 2 seconds..."
        )

        time.sleep(2)

@app.route("/web_api/<path:api_path>", methods=["GET", "POST"])
def web_api_proxy(api_path):
    print(f"[WEB PROXY] {request.method} {api_path}")
    if not api_path.startswith("api/"):
        return jsonify({
            "ok": False,
            "message": "Invalid API path"
        }), 400

    target_url = f"{API_SERVER_URL.rstrip('/')}/{api_path}"

    authorization_headers = {
        "Authorization": f"Bearer {API_KEY}"
    }

    try:
        if request.method == "GET":
            response = requests.get(
                target_url,
                headers=authorization_headers,
                params=request.args,
                timeout=10
            )

        else:
            response = requests.post(
                target_url,
                headers={
                    **authorization_headers,
                    "Content-Type": "application/json"
                },
                json=request.get_json(silent=True) or {},
                timeout=10
            )

        return (
            response.content,
            response.status_code,
            {
                "Content-Type": response.headers.get(
                    "Content-Type",
                    "application/json"
                )
            }
        )

    except requests.Timeout:
        return jsonify({
            "ok": False,
            "message": "API server response timeout"
        }), 504

    except requests.RequestException as error:
        return jsonify({
            "ok": False,
            "message": "Cannot connect to API server",
            "error": str(error)
        }), 502


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False
    )