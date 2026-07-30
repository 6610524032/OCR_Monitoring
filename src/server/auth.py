import hmac
from functools import wraps

from flask import (
    jsonify,
    request,
)

from src.logger import create_logger
from src.server.config import API_KEY


logger = create_logger(
    "server.auth"
)


MAX_AUTHORIZATION_HEADER_LENGTH = 4096


def _extract_bearer_token(
    authorization_header,
):
    """
    Extract an API key from:

        Authorization: Bearer <api-key>

    Returns None when the header is missing
    or malformed.
    """
    if not isinstance(
        authorization_header,
        str,
    ):
        return None

    if (
        not authorization_header
        or len(
            authorization_header
        )
        > MAX_AUTHORIZATION_HEADER_LENGTH
        or "\x00" in authorization_header
    ):
        return None

    parts = (
        authorization_header
        .strip()
        .split()
    )

    if len(
        parts
    ) != 2:
        return None

    scheme, token = parts

    if (
        scheme.casefold()
        != "bearer"
    ):
        return None

    token = token.strip()

    if not token:
        return None

    return token


def _encode_for_comparison(
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


def _api_key_matches(
    provided_api_key,
):
    """
    Compare API keys using bytes so compare_digest
    also works with non-ASCII characters.
    """
    provided_bytes = (
        _encode_for_comparison(
            provided_api_key
        )
    )

    expected_bytes = (
        _encode_for_comparison(
            API_KEY
        )
    )

    if (
        provided_bytes is None
        or expected_bytes is None
        or not expected_bytes
    ):
        return False

    return hmac.compare_digest(
        provided_bytes,
        expected_bytes,
    )


def _client_address():
    address = request.remote_addr

    if not address:
        return "unknown"

    return str(
        address
    )[:100]


def _unauthorized_response():
    response = jsonify({
        "ok": False,
        "message": (
            "Invalid or missing API key"
        ),
    })

    response.status_code = 401

    response.headers[
        "WWW-Authenticate"
    ] = (
        'Bearer realm="OCR Clean API"'
    )

    response.headers[
        "Cache-Control"
    ] = "no-store"

    return response


def require_api_key(
    function,
):
    @wraps(
        function
    )
    def wrapper(
        *args,
        **kwargs,
    ):
        authorization_header = (
            request.headers.get(
                "Authorization",
                "",
            )
        )

        provided_api_key = (
            _extract_bearer_token(
                authorization_header
            )
        )

        if (
            provided_api_key is None
            or not _api_key_matches(
                provided_api_key
            )
        ):
            logger.warning(
                (
                    "Unauthorized API request: "
                    "client=%s, method=%s, path=%s"
                ),
                _client_address(),
                request.method,
                request.path,
            )

            return _unauthorized_response()

        return function(
            *args,
            **kwargs,
        )

    return wrapper