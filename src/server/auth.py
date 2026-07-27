from functools import wraps

from flask import jsonify, request

from src.logger import create_logger
from src.server.config import API_KEY


logger = create_logger(
    "server.auth"
)


def require_api_key(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get(
            "Authorization",
            "",
        )

        expected_header = (
            f"Bearer {API_KEY}"
        )

        if auth_header != expected_header:
            logger.warning(
                "Unauthorized API request from %s",
                request.remote_addr,
            )

            return (
                jsonify(
                    {
                        "ok": False,
                        "message": (
                            "Invalid or missing API key"
                        ),
                    }
                ),
                401,
            )

        return func(
            *args,
            **kwargs,
        )

    return wrapper