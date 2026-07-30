import hashlib
import hmac
import os
import secrets
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

from flask import (
    g,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

from src.logger import create_logger


logger = create_logger(
    "web.auth"
)


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

ENV_FILE_PATH = (
    PROJECT_ROOT
    / ".env"
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


MAX_USERNAME_LENGTH = 256
MAX_PASSWORD_LENGTH = 4096
MAX_SECRET_LENGTH = 8192
MAX_CSRF_TOKEN_LENGTH = 512
MAX_NEXT_PATH_LENGTH = 2048

SESSION_VERSION = 1


_TEMPORARY_SECRET = (
    secrets.token_urlsafe(
        48
    )
)


def _load_environment_file() -> bool:
    """
    Load .env when python-dotenv is installed.

    Missing python-dotenv must not prevent the Web
    process from starting. System environment
    variables will still be available.
    """
    try:
        from dotenv import (
            load_dotenv,
        )

    except ImportError:
        logger.warning(
            (
                "python-dotenv is unavailable; "
                "using system environment "
                "variables only"
            )
        )

        return False

    try:
        return bool(
            load_dotenv(
                ENV_FILE_PATH,
                override=False,
            )
        )

    except OSError:
        logger.exception(
            (
                "Failed to read the Web "
                "environment file"
            )
        )

        return False

    except Exception:
        logger.exception(
            (
                "Unexpected error while loading "
                "the Web environment file"
            )
        )

        return False


_ENV_FILE_LOADED = (
    _load_environment_file()
)


def _get_environment_value(
    name,
    *,
    strip=False,
    maximum_length=None,
):
    value = os.getenv(
        name,
        "",
    )

    if not isinstance(
        value,
        str,
    ):
        value = str(
            value
        )

    if strip:
        value = value.strip()

    if (
        maximum_length is not None
        and len(
            value
        ) > maximum_length
    ):
        logger.error(
            (
                "Environment variable %s "
                "exceeds the allowed length"
            ),
            name,
        )

        return ""

    return value


def get_login_username():
    return _get_environment_value(
        WEB_LOGIN_USERNAME_ENV,
        strip=True,
        maximum_length=(
            MAX_USERNAME_LENGTH
        ),
    )


def get_login_password():
    return _get_environment_value(
        WEB_LOGIN_PASSWORD_ENV,
        strip=False,
        maximum_length=(
            MAX_PASSWORD_LENGTH
        ),
    )


def get_session_secret():
    configured_secret = (
        _get_environment_value(
            WEB_SECRET_KEY_ENV,
            strip=True,
            maximum_length=(
                MAX_SECRET_LENGTH
            ),
        )
    )

    if configured_secret:
        return configured_secret

    # ใช้เพื่อให้ Web Process เปิดได้เท่านั้น
    # Login จะยังถูกปิดเมื่อ WEB_SECRET_KEY ไม่มี
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

    configured_secret = (
        _get_environment_value(
            WEB_SECRET_KEY_ENV,
            strip=True,
            maximum_length=(
                MAX_SECRET_LENGTH
            ),
        )
    )

    if not configured_secret:
        missing_variables.append(
            WEB_SECRET_KEY_ENV
        )

    return missing_variables


def _encode_text(
    value,
):
    if not isinstance(
        value,
        str,
    ):
        return None

    try:
        return value.encode(
            "utf-8",
            errors="strict",
        )

    except UnicodeError:
        return None


def compare_text_securely(
    left_value,
    right_value,
):
    """
    Compare Unicode text using UTF-8 bytes and
    constant-time comparison.
    """
    left_bytes = _encode_text(
        left_value
    )

    right_bytes = _encode_text(
        right_value
    )

    if (
        left_bytes is None
        or right_bytes is None
    ):
        return False

    return hmac.compare_digest(
        left_bytes,
        right_bytes,
    )


def _credential_fingerprint():
    """
    Create a non-reversible fingerprint for the
    current login configuration.

    Existing sessions become invalid automatically
    after Username, Password, or Secret changes.
    """
    username = get_login_username()
    password = get_login_password()
    secret = get_session_secret()

    if (
        not username
        or not password
        or not secret
    ):
        return ""

    secret_bytes = _encode_text(
        secret
    )

    credential_bytes = _encode_text(
        (
            username
            + "\x00"
            + password
            + "\x00"
            + str(
                SESSION_VERSION
            )
        )
    )

    if (
        secret_bytes is None
        or credential_bytes is None
    ):
        return ""

    return hmac.new(
        secret_bytes,
        credential_bytes,
        hashlib.sha256,
    ).hexdigest()


def authenticate_login(
    username,
    password,
):
    """
    Validate submitted login credentials.

    Both comparisons are always performed before
    returning to reduce observable differences.
    """
    if get_missing_login_environment():
        return False

    if not isinstance(
        username,
        str,
    ):
        return False

    if not isinstance(
        password,
        str,
    ):
        return False

    submitted_username = (
        username.strip()
    )

    submitted_password = password

    if (
        not submitted_username
        or len(
            submitted_username
        ) > MAX_USERNAME_LENGTH
        or len(
            submitted_password
        ) > MAX_PASSWORD_LENGTH
        or "\x00" in submitted_username
        or "\x00" in submitted_password
    ):
        return False

    username_matches = (
        compare_text_securely(
            submitted_username,
            get_login_username(),
        )
    )

    password_matches = (
        compare_text_securely(
            submitted_password,
            get_login_password(),
        )
    )

    return bool(
        username_matches
        and password_matches
    )


def create_login_session():
    """
    Replace the previous session completely after
    successful authentication.
    """
    configured_username = (
        get_login_username()
    )

    fingerprint = (
        _credential_fingerprint()
    )

    if (
        not configured_username
        or not fingerprint
        or get_missing_login_environment()
    ):
        raise RuntimeError(
            (
                "Web login environment "
                "is not configured"
            )
        )

    session.clear()

    session.permanent = True

    session[
        "web_authenticated"
    ] = True

    session[
        "web_username"
    ] = configured_username

    session[
        "web_session_version"
    ] = SESSION_VERSION

    session[
        "web_credential_fingerprint"
    ] = fingerprint

    session[
        "_csrf_token"
    ] = secrets.token_urlsafe(
        32
    )

    session.modified = True


def clear_login_session():
    """
    Remove all Web login and CSRF information.
    """
    session.clear()
    session.modified = True


def get_current_user():
    if not session.get(
        "web_authenticated"
    ):
        return None

    if get_missing_login_environment():
        clear_login_session()
        return None

    configured_username = (
        get_login_username()
    )

    session_username = session.get(
        "web_username",
        "",
    )

    session_version = session.get(
        "web_session_version"
    )

    stored_fingerprint = session.get(
        "web_credential_fingerprint",
        "",
    )

    expected_fingerprint = (
        _credential_fingerprint()
    )

    if not isinstance(
        session_username,
        str,
    ):
        clear_login_session()
        return None

    if not isinstance(
        stored_fingerprint,
        str,
    ):
        clear_login_session()
        return None

    username_matches = (
        compare_text_securely(
            session_username,
            configured_username,
        )
    )

    fingerprint_matches = (
        compare_text_securely(
            stored_fingerprint,
            expected_fingerprint,
        )
    )

    if (
        session_version != SESSION_VERSION
        or not username_matches
        or not fingerprint_matches
    ):
        clear_login_session()
        return None

    return {
        "username": (
            configured_username
        ),
    }


def get_csrf_token():
    token = session.get(
        "_csrf_token"
    )

    if (
        not isinstance(
            token,
            str,
        )
        or not token
        or len(
            token
        ) > MAX_CSRF_TOKEN_LENGTH
    ):
        token = secrets.token_urlsafe(
            32
        )

        session[
            "_csrf_token"
        ] = token

        session.modified = True

    return token


def validate_csrf_token(
    submitted_token,
):
    expected_token = session.get(
        "_csrf_token",
        "",
    )

    if not isinstance(
        expected_token,
        str,
    ):
        return False

    if not isinstance(
        submitted_token,
        str,
    ):
        return False

    if (
        not expected_token
        or not submitted_token
        or len(
            expected_token
        ) > MAX_CSRF_TOKEN_LENGTH
        or len(
            submitted_token
        ) > MAX_CSRF_TOKEN_LENGTH
    ):
        return False

    return compare_text_securely(
        expected_token,
        submitted_token,
    )


def is_safe_next_path(
    target,
):
    """
    Allow only local absolute paths such as:

        /dashboard
        /history?page=2

    External URLs, protocol-relative URLs,
    backslashes, and control characters are rejected.
    """
    if not isinstance(
        target,
        str,
    ):
        return False

    target = target.strip()

    if (
        not target
        or len(
            target
        ) > MAX_NEXT_PATH_LENGTH
        or not target.startswith(
            "/"
        )
        or target.startswith(
            "//"
        )
        or "\\" in target
        or "\x00" in target
        or any(
            ord(
                character
            ) < 32
            for character in target
        )
    ):
        return False

    try:
        parsed = urlsplit(
            target
        )

    except ValueError:
        return False

    return (
        parsed.scheme == ""
        and parsed.netloc == ""
    )


def _resolve_current_user():
    current_user = getattr(
        g,
        "current_user",
        None,
    )

    if current_user is None:
        current_user = (
            get_current_user()
        )

        g.current_user = (
            current_user
        )

    return current_user


def _login_redirect():
    next_path = (
        request.full_path
        if request.query_string
        else request.path
    )

    if not is_safe_next_path(
        next_path
    ):
        next_path = "/"

    response = redirect(
        url_for(
            "login",
            next=next_path,
        )
    )

    response.headers[
        "Cache-Control"
    ] = "no-store"

    return response


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
        if (
            _resolve_current_user()
            is None
        ):
            return _login_redirect()

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
        if (
            _resolve_current_user()
            is None
        ):
            response = jsonify({
                "ok": False,
                "message": (
                    "Login session has expired"
                ),
                "login_required": True,
            })

            response.status_code = 401

            response.headers[
                "Cache-Control"
            ] = "no-store"

            return response

        return view_function(
            *args,
            **kwargs,
        )

    return wrapped_view