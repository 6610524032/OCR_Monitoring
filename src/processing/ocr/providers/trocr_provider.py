"""
TrOCR provider implementation.

This module contains code that is specific to the Hugging Face
TrOCR engine. Generic OCR code should not be placed here.
"""

import os
import re
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Any, Optional

import torch
from PIL import Image
from transformers import (
    TrOCRProcessor,
    VisionEncoderDecoderModel,
)

from src.logger import create_logger
from src.processing.ocr.model_status import (
    OCRModelStatus,
    set_model_status,
)
from src.server.config import (
    MODEL_CACHE_DIR,
    OCR_MODEL_NAME,
)


logger = create_logger(
    "processing.ocr.trocr_provider"
)


MAX_INPUT_DIMENSION = 4096
MAX_INPUT_PIXELS = 16_000_000
MAX_GENERATION_LENGTH = 40
MAX_RESULT_LENGTH = 500
MAX_ERROR_TEXT_LENGTH = 500


_CONTROL_CHARACTER_PATTERN = re.compile(
    r"[\x00-\x1f\x7f]"
)


class TrOCRProviderError(
    RuntimeError
):
    """
    Raised when the TrOCR provider cannot load
    or run the configured model.
    """


def _safe_error_text(
    error: BaseException,
) -> str:
    try:
        text = " ".join(
            str(
                error
            ).split()
        )

    except Exception:
        text = ""

    if not text:
        text = type(
            error
        ).__name__

    return text[
        :MAX_ERROR_TEXT_LENGTH
    ]


def _clean_result_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    try:
        text = str(
            value
        )

    except Exception:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        text,
    )

    text = _CONTROL_CHARACTER_PATTERN.sub(
        "",
        text,
    )

    return text.strip()[
        :MAX_RESULT_LENGTH
    ]


class TrOCRProvider:
    """
    OCR provider that uses Microsoft's TrOCR model.

    The provider loads the processor and model once and
    serializes model loading and inference for safe use
    from multiple threads.
    """

    def __init__(
        self,
    ) -> None:
        self.processor: Optional[
            TrOCRProcessor
        ] = None

        self.model: Optional[
            VisionEncoderDecoderModel
        ] = None

        self.device = torch.device(
            "cpu"
        )

        self._load_lock = Lock()
        self._inference_lock = Lock()

    def _prepare_cache(
        self,
    ) -> Path:
        """
        Prepare the Hugging Face cache directory.
        """
        cache_directory = Path(
            MODEL_CACHE_DIR
        )

        try:
            cache_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            resolved_cache = (
                cache_directory.resolve()
            )

        except OSError as error:
            logger.exception(
                (
                    "Cannot prepare TrOCR "
                    "cache directory: %s"
                ),
                cache_directory,
            )

            raise TrOCRProviderError(
                (
                    "Cannot prepare the "
                    "TrOCR cache directory"
                )
            ) from error

        cache_text = str(
            resolved_cache
        )

        # HF_HOME และ HF_HUB_CACHE เป็นตัวแปรหลัก
        # ส่วน HUGGINGFACE_HUB_CACHE คงไว้เพื่อรองรับ
        # ไลบรารีหรือสภาพแวดล้อมเดิม
        os.environ[
            "HF_HOME"
        ] = cache_text

        os.environ[
            "HF_HUB_CACHE"
        ] = cache_text

        os.environ[
            "HUGGINGFACE_HUB_CACHE"
        ] = cache_text

        os.environ.setdefault(
            "TOKENIZERS_PARALLELISM",
            "false",
        )

        logger.debug(
            (
                "TrOCR cache directory "
                "prepared: %s"
            ),
            resolved_cache,
        )

        return resolved_cache

    def _load_processor(
        self,
        cache_directory: Path,
    ) -> TrOCRProcessor:
        """
        Load the processor from the local cache first.

        When it is unavailable or incomplete, allow
        Hugging Face to download the required files.
        """
        logger.info(
            (
                "Loading TrOCR processor "
                "from local cache"
            )
        )

        try:
            processor = (
                TrOCRProcessor.from_pretrained(
                    OCR_MODEL_NAME,
                    cache_dir=str(
                        cache_directory
                    ),
                    local_files_only=True,
                    use_fast=False,
                )
            )

            logger.info(
                (
                    "TrOCR processor loaded "
                    "from local cache"
                )
            )

            return processor

        except Exception as cache_error:
            logger.info(
                (
                    "TrOCR processor is not "
                    "available in the local "
                    "cache; download will be "
                    "attempted"
                )
            )

            logger.debug(
                (
                    "Local TrOCR processor "
                    "load failed: %s"
                ),
                _safe_error_text(
                    cache_error
                ),
            )

        set_model_status(
            OCRModelStatus.DOWNLOADING,
            "Downloading TrOCR processor",
        )

        logger.info(
            "Downloading TrOCR processor"
        )

        try:
            processor = (
                TrOCRProcessor.from_pretrained(
                    OCR_MODEL_NAME,
                    cache_dir=str(
                        cache_directory
                    ),
                    local_files_only=False,
                    use_fast=False,
                )
            )

        except Exception as error:
            logger.exception(
                (
                    "Failed to download or "
                    "load TrOCR processor"
                )
            )

            raise TrOCRProviderError(
                (
                    "Failed to load the "
                    "TrOCR processor"
                )
            ) from error

        logger.info(
            (
                "TrOCR processor downloaded "
                "and loaded successfully"
            )
        )

        return processor

    def _load_model(
        self,
        cache_directory: Path,
    ) -> VisionEncoderDecoderModel:
        """
        Load the model from the local cache first.

        When it is unavailable or incomplete, allow
        Hugging Face to download the required files.
        """
        logger.info(
            (
                "Loading TrOCR model "
                "from local cache"
            )
        )

        try:
            model = (
                VisionEncoderDecoderModel
                .from_pretrained(
                    OCR_MODEL_NAME,
                    cache_dir=str(
                        cache_directory
                    ),
                    local_files_only=True,
                )
            )

            logger.info(
                (
                    "TrOCR model loaded "
                    "from local cache"
                )
            )

        except Exception as cache_error:
            logger.info(
                (
                    "TrOCR model is not "
                    "available in the local "
                    "cache; download will be "
                    "attempted"
                )
            )

            logger.debug(
                (
                    "Local TrOCR model load "
                    "failed: %s"
                ),
                _safe_error_text(
                    cache_error
                ),
            )

            set_model_status(
                OCRModelStatus.DOWNLOADING,
                "Downloading TrOCR model",
            )

            logger.info(
                "Downloading TrOCR model"
            )

            try:
                model = (
                    VisionEncoderDecoderModel
                    .from_pretrained(
                        OCR_MODEL_NAME,
                        cache_dir=str(
                            cache_directory
                        ),
                        local_files_only=False,
                    )
                )

            except Exception as error:
                logger.exception(
                    (
                        "Failed to download "
                        "or load TrOCR model"
                    )
                )

                raise TrOCRProviderError(
                    (
                        "Failed to load the "
                        "TrOCR model"
                    )
                ) from error

            logger.info(
                (
                    "TrOCR model downloaded "
                    "successfully"
                )
            )

        try:
            model.to(
                self.device
            )

            model.eval()

            model.requires_grad_(
                False
            )

        except Exception as error:
            logger.exception(
                (
                    "Cannot prepare TrOCR "
                    "model for CPU inference"
                )
            )

            raise TrOCRProviderError(
                (
                    "Cannot prepare the "
                    "TrOCR model"
                )
            ) from error

        return model

    def load_model(
        self,
    ) -> tuple[
        TrOCRProcessor,
        VisionEncoderDecoderModel,
    ]:
        """
        Load the TrOCR processor and model into memory.

        Model objects are assigned to the provider only
        after both components have loaded successfully.
        """
        if (
            self.processor is not None
            and self.model is not None
        ):
            return (
                self.processor,
                self.model,
            )

        with self._load_lock:
            # ตรวจซ้ำหลังได้ Lock เพราะ Thread อื่น
            # อาจโหลดโมเดลเสร็จแล้วระหว่างรอ
            if (
                self.processor is not None
                and self.model is not None
            ):
                return (
                    self.processor,
                    self.model,
                )

            logger.info(
                (
                    "Starting TrOCR model "
                    "preparation: model=%s, "
                    "device=%s"
                ),
                OCR_MODEL_NAME,
                self.device,
            )

            processor = None
            model = None

            try:
                set_model_status(
                    OCRModelStatus.CHECKING,
                    (
                        "Checking TrOCR "
                        "model cache"
                    ),
                )

                cache_directory = (
                    self._prepare_cache()
                )

                set_model_status(
                    OCRModelStatus.LOADING,
                    (
                        "Loading TrOCR "
                        "processor"
                    ),
                )

                processor = (
                    self._load_processor(
                        cache_directory
                    )
                )

                set_model_status(
                    OCRModelStatus.LOADING,
                    "Loading TrOCR model",
                )

                model = self._load_model(
                    cache_directory
                )

                # กำหนดค่าหลังโหลดครบทั้งสองส่วน
                # เพื่อไม่ให้ Provider ค้างในสถานะครึ่งหนึ่ง
                self.processor = processor
                self.model = model

                set_model_status(
                    OCRModelStatus.READY,
                    "TrOCR model is ready",
                )

                logger.info(
                    (
                        "TrOCR model preparation "
                        "completed successfully"
                    )
                )

                return (
                    self.processor,
                    self.model,
                )

            except Exception as error:
                self.processor = None
                self.model = None

                error_text = (
                    _safe_error_text(
                        error
                    )
                )

                set_model_status(
                    OCRModelStatus.ERROR,
                    (
                        "Failed to load "
                        "TrOCR model"
                    ),
                    error_text,
                )

                logger.exception(
                    (
                        "TrOCR model "
                        "preparation failed"
                    )
                )

                raise

    def _validate_image(
        self,
        image: Any,
    ) -> Image.Image:
        if not isinstance(
            image,
            Image.Image,
        ):
            raise TrOCRProviderError(
                (
                    "TrOCR input must be "
                    "a PIL image"
                )
            )

        width, height = image.size

        if (
            width <= 0
            or height <= 0
        ):
            raise TrOCRProviderError(
                (
                    "TrOCR input image "
                    "is empty"
                )
            )

        if (
            width > MAX_INPUT_DIMENSION
            or height > MAX_INPUT_DIMENSION
        ):
            raise TrOCRProviderError(
                (
                    "TrOCR input image "
                    "dimensions are too large"
                )
            )

        if (
            width
            * height
            > MAX_INPUT_PIXELS
        ):
            raise TrOCRProviderError(
                (
                    "TrOCR input image "
                    "contains too many pixels"
                )
            )

        return image

    def _get_pixel_values(
        self,
        processor: TrOCRProcessor,
        image: Image.Image,
    ) -> torch.Tensor:
        try:
            processor_output = processor(
                images=image,
                return_tensors="pt",
            )

        except Exception as error:
            raise TrOCRProviderError(
                (
                    "TrOCR processor cannot "
                    "prepare the input image"
                )
            ) from error

        pixel_values = getattr(
            processor_output,
            "pixel_values",
            None,
        )

        if (
            pixel_values is None
            and isinstance(
                processor_output,
                Mapping,
            )
        ):
            pixel_values = (
                processor_output.get(
                    "pixel_values"
                )
            )

        if not torch.is_tensor(
            pixel_values
        ):
            raise TrOCRProviderError(
                (
                    "TrOCR processor returned "
                    "invalid pixel values"
                )
            )

        if pixel_values.numel() <= 0:
            raise TrOCRProviderError(
                (
                    "TrOCR processor returned "
                    "empty pixel values"
                )
            )

        try:
            return pixel_values.to(
                device=self.device,
                non_blocking=False,
            )

        except Exception as error:
            raise TrOCRProviderError(
                (
                    "Cannot move TrOCR input "
                    "to the CPU"
                )
            ) from error

    def read(
        self,
        image: Image.Image,
    ) -> str:
        """
        Read text from a PIL image using TrOCR.

        Empty decoded output is a valid OCR result and
        returns an empty string. Model or inference
        failures raise an exception to the caller.
        """
        validated_image = (
            self._validate_image(
                image
            )
        )

        converted_image = None

        try:
            if validated_image.mode == "RGB":
                inference_image = (
                    validated_image
                )

            else:
                converted_image = (
                    validated_image.convert(
                        "RGB"
                    )
                )

                inference_image = (
                    converted_image
                )

            with self._inference_lock:
                processor, model = (
                    self.load_model()
                )

                pixel_values = (
                    self._get_pixel_values(
                        processor=processor,
                        image=inference_image,
                    )
                )

                try:
                    with torch.inference_mode():
                        generated_ids = (
                            model.generate(
                                pixel_values,
                                max_length=(
                                    MAX_GENERATION_LENGTH
                                ),
                            )
                        )

                    decoded_text = (
                        processor.batch_decode(
                            generated_ids,
                            skip_special_tokens=True,
                        )
                    )

                except Exception as error:
                    raise TrOCRProviderError(
                        (
                            "TrOCR inference "
                            "failed"
                        )
                    ) from error

            if not isinstance(
                decoded_text,
                (
                    list,
                    tuple,
                ),
            ):
                raise TrOCRProviderError(
                    (
                        "TrOCR decoder returned "
                        "an invalid result"
                    )
                )

            if not decoded_text:
                logger.debug(
                    (
                        "TrOCR completed without "
                        "decoded text"
                    )
                )

                return ""

            result_text = (
                _clean_result_text(
                    decoded_text[0]
                )
            )

            if not result_text:
                logger.debug(
                    (
                        "TrOCR returned an "
                        "empty text result"
                    )
                )

                return ""

            logger.debug(
                (
                    "TrOCR inference completed "
                    "successfully"
                )
            )

            return result_text

        except TrOCRProviderError:
            logger.exception(
                "TrOCR inference failed"
            )

            raise

        except MemoryError as error:
            logger.exception(
                (
                    "TrOCR inference failed "
                    "because memory was "
                    "insufficient"
                )
            )

            raise TrOCRProviderError(
                (
                    "Insufficient memory for "
                    "TrOCR inference"
                )
            ) from error

        except Exception as error:
            logger.exception(
                (
                    "Unexpected TrOCR "
                    "inference error"
                )
            )

            raise TrOCRProviderError(
                (
                    "Unexpected TrOCR "
                    "inference error"
                )
            ) from error

        finally:
            if converted_image is not None:
                try:
                    converted_image.close()

                except Exception:
                    logger.debug(
                        (
                            "Cannot close converted "
                            "TrOCR input image"
                        )
                    )


_TROCR_PROVIDER: Optional[
    TrOCRProvider
] = None

_TROCR_PROVIDER_LOCK = Lock()


def get_trocr_provider(
) -> TrOCRProvider:
    """
    Return the shared TrOCR provider instance.
    """
    global _TROCR_PROVIDER

    if _TROCR_PROVIDER is not None:
        return _TROCR_PROVIDER

    with _TROCR_PROVIDER_LOCK:
        if _TROCR_PROVIDER is None:
            logger.info(
                (
                    "Creating shared TrOCR "
                    "provider instance"
                )
            )

            _TROCR_PROVIDER = (
                TrOCRProvider()
            )

    return _TROCR_PROVIDER