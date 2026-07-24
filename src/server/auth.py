from functools import wraps

from flask import jsonify, request

from src.server.config import API_KEY


def require_api_key(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")

        expected_header = f"Bearer {API_KEY}"

        if auth_header != expected_header:
            return jsonify({
                "ok": False,
                "message": "Invalid or missing API key"
            }), 401

        return func(*args, **kwargs)

    return wrapper