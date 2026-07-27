import hmac
import os
import secrets
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from flask import (
    g,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from src.logger import create_logger


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

load_dotenv(
    PROJECT_ROOT / ".env",
    override=False,
)


logger = create_logger(
    "web.auth"
)


WEB_LOGIN_USERNAME_ENV = (
    "WEB_LOGIN_USERNAME"
)

WEB_LOGIN_PASSWORD_ENV = (
    "WEB_LOGIN_PASSWORD"
)

WEB_SECRET_KEY_ENV = (
    "WEB_SECRET_KEY"
)


_TEMPORARY_SECRET = (
    secrets.token_urlsafe(48)
)


def get_login_username():
    return os.getenv(
        WEB_LOGIN_USERNAME_ENV,
        "",
    ).strip()


def get_login_password():
    return os.getenv(
        WEB_LOGIN_PASSWORD_ENV,
        "",
    )


def get_session_secret():
    configured_secret = os.getenv(
        WEB_SECRET_KEY_ENV,
        "",
    ).strip()

    if configured_secret:
        return configured_secret

    return _TEMPORARY_SECRET


def get_missing_login_environment():
    missing_variables = []

    if not get_login_username():
        missing_variables.append(
            WEB_LOGIN_USERNAME_ENV
        )

    if not get_login_password():
        missing_variables.append(
            WEB_LOGIN_PASSWORD_ENV
        )

    if not os.getenv(
        WEB_SECRET_KEY_ENV,
        "",
    ).strip():
        missing_variables.append(
            WEB_SECRET_KEY_ENV
        )

    return missing_variables


def compare_text_securely(
    left_value,
    right_value,
):
    left_bytes = str(
        left_value
        or ""
    ).encode(
        "utf-8"
    )

    right_bytes = str(
        right_value
        or ""
    ).encode(
        "utf-8"
    )

    return hmac.compare_digest(
        left_bytes,
        right_bytes,
    )


def authenticate_login(
    username,
    password,
):
    if get_missing_login_environment():
        return False

    submitted_username = str(
        username
        or ""
    )

    submitted_password = str(
        password
        or ""
    )

    username_matches = compare_text_securely(
        submitted_username,
        get_login_username(),
    )

    password_matches = compare_text_securely(
        submitted_password,
        get_login_password(),
    )

    return (
        username_matches
        and password_matches
    )


def create_login_session():
    session.clear()
    session.permanent = True

    session[
        "web_authenticated"
    ] = True

    session[
        "web_username"
    ] = get_login_username()

    session[
        "_csrf_token"
    ] = secrets.token_urlsafe(
        32
    )


def get_current_user():
    if not session.get(
        "web_authenticated"
    ):
        return None

    configured_username = (
        get_login_username()
    )

    session_username = str(
        session.get(
            "web_username",
            "",
        )
    )

    if (
        not configured_username
        or not session_username
    ):
        session.clear()
        return None

    if not compare_text_securely(
        session_username,
        configured_username,
    ):
        session.clear()
        return None

    return {
        "username": configured_username,
    }


def get_csrf_token():
    token = session.get(
        "_csrf_token"
    )

    if not token:
        token = secrets.token_urlsafe(
            32
        )

        session[
            "_csrf_token"
        ] = token

    return str(
        token
    )


def validate_csrf_token(
    submitted_token,
):
    expected_token = str(
        session.get(
            "_csrf_token",
            "",
        )
    )

    submitted_token = str(
        submitted_token
        or ""
    )

    if (
        not expected_token
        or not submitted_token
    ):
        return False

    return hmac.compare_digest(
        expected_token,
        submitted_token,
    )


def is_safe_next_path(
    target,
):
    target = str(
        target
        or ""
    ).strip()

    if not target:
        return False

    parsed = urlsplit(
        target
    )

    return (
        parsed.scheme == ""
        and parsed.netloc == ""
        and target.startswith("/")
        and not target.startswith("//")
    )


def login_required(
    view_function,
):
    @wraps(
        view_function
    )
    def wrapped_view(
        *args,
        **kwargs,
    ):
        current_user = getattr(
            g,
            "current_user",
            None,
        )

        if current_user is None:
            next_path = (
                request.full_path
                if request.query_string
                else request.path
            )

            return redirect(
                url_for(
                    "login",
                    next=next_path,
                )
            )

        return view_function(
            *args,
            **kwargs,
        )

    return wrapped_view


def login_required_json(
    view_function,
):
    @wraps(
        view_function
    )
    def wrapped_view(
        *args,
        **kwargs,
    ):
        current_user = getattr(
            g,
            "current_user",
            None,
        )

        if current_user is None:
            return jsonify({
                "ok": False,
                "message": (
                    "Login session has expired"
                ),
                "login_required": True,
            }), 401

        return view_function(
            *args,
            **kwargs,
        )

    return wrapped_view