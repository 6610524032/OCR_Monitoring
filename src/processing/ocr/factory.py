"""
OCR provider factory.

This module selects and returns the OCR provider configured
through the OCR_ENGINE environment setting.
"""

import os
from threading import Lock
from typing import (
    Any,
    Callable,
    Optional,
    Protocol,
    cast,
    runtime_checkable,
)

from src.logger import create_logger
from src.processing.ocr.providers.trocr_provider import (
    get_trocr_provider,
)
from src.server.config import (
    OCR_ENGINE as DEFAULT_OCR_ENGINE,
)


logger = create_logger(
    "processing.ocr.factory"
)


class OCRConfigurationError(
    ValueError
):
    """
    Raised when OCR engine configuration
    is missing or unsupported.
    """


@runtime_checkable
class OCRProvider(
    Protocol
):
    """
    Minimum interface required from
    an OCR provider.
    """

    def read(
        self,
        image: Any,
    ) -> str:
        ...


ProviderFactory = Callable[
    [],
    OCRProvider,
]


_PROVIDER_FACTORIES: dict[
    str,
    ProviderFactory,
] = {
    "trocr": get_trocr_provider,
}


SUPPORTED_OCR_ENGINES = frozenset(
    _PROVIDER_FACTORIES
)


_OCR_PROVIDER: Optional[
    OCRProvider
] = None

_ACTIVE_OCR_ENGINE: Optional[
    str
] = None

_OCR_PROVIDER_LOCK = Lock()


def _get_configured_engine_value(
) -> str:
    """
    Read OCR_ENGINE from the current environment.

    DEFAULT_OCR_ENGINE is used when the environment
    variable is absent.
    """
    if DEFAULT_OCR_ENGINE is None:
        fallback_value = ""

    else:
        fallback_value = str(
            DEFAULT_OCR_ENGINE
        )

    return os.getenv(
        "OCR_ENGINE",
        fallback_value,
    )


def validate_ocr_engine(
    engine_name: Any = None,
) -> str:
    """
    Validate and normalize an OCR engine name.

    When engine_name is omitted, the current
    OCR_ENGINE environment value is used.
    """
    raw_engine_name = (
        _get_configured_engine_value()
        if engine_name is None
        else engine_name
    )

    if isinstance(
        raw_engine_name,
        bool,
    ):
        normalized_name = ""

    else:
        try:
            normalized_name = str(
                raw_engine_name
            ).strip().casefold()

        except Exception as error:
            raise OCRConfigurationError(
                (
                    "OCR engine configuration "
                    "cannot be read"
                )
            ) from error

    supported_text = ", ".join(
        sorted(
            SUPPORTED_OCR_ENGINES
        )
    )

    if not normalized_name:
        logger.error(
            (
                "OCR engine configuration "
                "is empty"
            )
        )

        raise OCRConfigurationError(
            (
                "OCR_ENGINE is required. "
                f"Supported engines: "
                f"{supported_text}"
            )
        )

    if (
        normalized_name
        not in SUPPORTED_OCR_ENGINES
    ):
        logger.error(
            (
                "Unsupported OCR engine: %s"
            ),
            normalized_name[
                :100
            ],
        )

        raise OCRConfigurationError(
            (
                "Unsupported OCR engine: "
                f"{normalized_name}. "
                "Supported engines: "
                f"{supported_text}"
            )
        )

    return normalized_name


def _validate_provider(
    provider: Any,
    engine_name: str,
) -> OCRProvider:
    if provider is None:
        raise OCRConfigurationError(
            (
                "OCR provider factory "
                f"returned no provider for "
                f"engine: {engine_name}"
            )
        )

    read_method = getattr(
        provider,
        "read",
        None,
    )

    if not callable(
        read_method
    ):
        raise OCRConfigurationError(
            (
                "OCR provider does not "
                "implement a callable "
                f"read() method: {engine_name}"
            )
        )

    return cast(
        OCRProvider,
        provider,
    )


def create_ocr_provider(
    engine_name: Any = None,
) -> OCRProvider:
    """
    Create or obtain the provider selected
    by the requested OCR engine.

    The provider is assigned to the factory cache
    only after successful creation and validation.
    """
    validated_engine = (
        validate_ocr_engine(
            engine_name
        )
    )

    provider_factory = (
        _PROVIDER_FACTORIES.get(
            validated_engine
        )
    )

    if provider_factory is None:
        logger.error(
            (
                "No OCR provider factory "
                "is registered for engine: %s"
            ),
            validated_engine,
        )

        raise OCRConfigurationError(
            (
                "No provider implementation "
                "was found for OCR engine: "
                f"{validated_engine}"
            )
        )

    logger.info(
        (
            "Creating OCR provider: "
            "engine=%s"
        ),
        validated_engine,
    )

    try:
        provider = (
            provider_factory()
        )

    except Exception:
        logger.exception(
            (
                "OCR provider creation "
                "failed: engine=%s"
            ),
            validated_engine,
        )

        raise

    try:
        return _validate_provider(
            provider=provider,
            engine_name=(
                validated_engine
            ),
        )

    except OCRConfigurationError:
        logger.exception(
            (
                "OCR provider validation "
                "failed: engine=%s"
            ),
            validated_engine,
        )

        raise


def get_ocr_provider(
) -> OCRProvider:
    """
    Return the shared OCR provider instance.

    Provider creation is protected by a lock.
    The provider is recreated when OCR_ENGINE
    changes during the current Python process.
    """
    global _OCR_PROVIDER
    global _ACTIVE_OCR_ENGINE

    engine_name = (
        validate_ocr_engine()
    )

    if (
        _OCR_PROVIDER is not None
        and _ACTIVE_OCR_ENGINE
        == engine_name
    ):
        return _OCR_PROVIDER

    with _OCR_PROVIDER_LOCK:
        # อ่านค่าอีกครั้งหลังได้ Lock เพราะ
        # Environment อาจเปลี่ยนระหว่างรอ
        engine_name = (
            validate_ocr_engine()
        )

        if (
            _OCR_PROVIDER is not None
            and _ACTIVE_OCR_ENGINE
            == engine_name
        ):
            return _OCR_PROVIDER

        provider = (
            create_ocr_provider(
                engine_name
            )
        )

        # กำหนด Global หลังสร้าง Provider
        # สำเร็จแล้วเท่านั้น หากล้มเหลวจะยัง
        # รักษา Provider เดิมไว้
        _OCR_PROVIDER = provider
        _ACTIVE_OCR_ENGINE = (
            engine_name
        )

        logger.info(
            (
                "OCR provider initialized: "
                "engine=%s, provider=%s"
            ),
            engine_name,
            type(
                provider
            ).__name__,
        )

        return provider


def get_active_ocr_engine(
) -> str:
    """
    Return the validated OCR engine currently
    configured in the environment.
    """
    return validate_ocr_engine()