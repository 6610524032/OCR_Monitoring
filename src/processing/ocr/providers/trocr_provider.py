"""
TrOCR provider implementation.

This module contains code that is specific to the Hugging Face
TrOCR engine. Generic OCR code should not be placed here.
"""

import os
from typing import Optional

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


class TrOCRProvider:
    """
    OCR provider that uses Microsoft's TrOCR model.
    """

    def __init__(self) -> None:
        self.processor: Optional[
            TrOCRProcessor
        ] = None

        self.model: Optional[
            VisionEncoderDecoderModel
        ] = None

    def _prepare_cache(self) -> None:
        """
        Prepare Hugging Face cache directory.
        """
        try:
            MODEL_CACHE_DIR.mkdir(
                parents=True,
                exist_ok=True,
            )

            os.environ["HF_HOME"] = str(
                MODEL_CACHE_DIR
            )

            os.environ[
                "HUGGINGFACE_HUB_CACHE"
            ] = str(
                MODEL_CACHE_DIR
            )

        except Exception:
            logger.exception(
                "Cannot prepare TrOCR model cache directory: %s",
                MODEL_CACHE_DIR
            )
            raise

        logger.info(
            "TrOCR cache directory prepared: %s",
            MODEL_CACHE_DIR
        )

    def _load_processor(
        self,
    ) -> TrOCRProcessor:
        """
        Load the TrOCR processor.

        Try local cache first.
        Download automatically if necessary.
        """
        logger.info(
            "Loading TrOCR processor from local cache"
        )

        try:
            processor = (
                TrOCRProcessor.from_pretrained(
                    OCR_MODEL_NAME,
                    cache_dir=str(
                        MODEL_CACHE_DIR,
                    ),
                    local_files_only=True,
                    use_fast=False,
                )
            )

            logger.info(
                "TrOCR processor loaded from local cache"
            )

            return processor

        except Exception as cache_error:
            logger.warning(
                (
                    "TrOCR processor was not available "
                    "in local cache. Download will be attempted: %s"
                ),
                str(cache_error)
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
                        MODEL_CACHE_DIR,
                    ),
                    local_files_only=False,
                    use_fast=False,
                )
            )

        except Exception:
            logger.exception(
                "Failed to download TrOCR processor"
            )
            raise

        logger.info(
            "TrOCR processor downloaded successfully"
        )

        return processor

    def _load_model(
        self,
    ) -> VisionEncoderDecoderModel:
        """
        Load the TrOCR model.

        Try local cache first.
        Download automatically if necessary.
        """
        logger.info(
            "Loading TrOCR model from local cache"
        )

        try:
            model = (
                VisionEncoderDecoderModel.from_pretrained(
                    OCR_MODEL_NAME,
                    cache_dir=str(
                        MODEL_CACHE_DIR,
                    ),
                    local_files_only=True,
                )
            )

            logger.info(
                "TrOCR model loaded from local cache"
            )

        except Exception as cache_error:
            logger.warning(
                (
                    "TrOCR model was not available "
                    "in local cache. Download will be attempted: %s"
                ),
                str(cache_error)
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
                    VisionEncoderDecoderModel.from_pretrained(
                        OCR_MODEL_NAME,
                        cache_dir=str(
                            MODEL_CACHE_DIR,
                        ),
                        local_files_only=False,
                    )
                )

            except Exception:
                logger.exception(
                    "Failed to download TrOCR model"
                )
                raise

            logger.info(
                "TrOCR model downloaded successfully"
            )

        try:
            model.eval()

        except Exception:
            logger.exception(
                "Cannot switch TrOCR model to evaluation mode"
            )
            raise

        return model

    def load_model(
        self,
    ) -> tuple[
        TrOCRProcessor,
        VisionEncoderDecoderModel,
    ]:
        """
        Load the TrOCR processor and model into memory.
        """
        if (
            self.processor is not None
            and self.model is not None
        ):
            return (
                self.processor,
                self.model,
            )

        logger.info(
            "Starting TrOCR model preparation: model=%s",
            OCR_MODEL_NAME
        )

        try:
            set_model_status(
                OCRModelStatus.CHECKING,
                "Checking TrOCR model cache",
            )

            self._prepare_cache()

            set_model_status(
                OCRModelStatus.LOADING,
                "Loading TrOCR processor",
            )

            self.processor = (
                self._load_processor()
            )

            logger.info(
                "TrOCR processor is ready"
            )

            set_model_status(
                OCRModelStatus.LOADING,
                "Loading TrOCR model",
            )

            self.model = (
                self._load_model()
            )

            logger.info(
                "TrOCR model is loaded into memory"
            )

            set_model_status(
                OCRModelStatus.READY,
                "TrOCR model is ready",
            )

            logger.info(
                "TrOCR model preparation completed successfully"
            )

            return (
                self.processor,
                self.model,
            )

        except Exception as exc:
            set_model_status(
                OCRModelStatus.ERROR,
                "Failed to load TrOCR model",
                str(exc),
            )

            logger.exception(
                "TrOCR model preparation failed"
            )

            raise


    def read(
        self,
        image: Image.Image,
    ) -> str:
        """
        Read text from a PIL image using TrOCR.
        """
        if image is None:
            logger.error(
                "Cannot run TrOCR because input image is None"
            )
            return ""

        try:
            processor, model = (
                self.load_model()
            )

            pixel_values = processor(
                images=image,
                return_tensors="pt",
            ).pixel_values

            generated_ids = model.generate(
                pixel_values,
                max_length=40,
            )

            decoded_text = (
                processor.batch_decode(
                    generated_ids,
                    skip_special_tokens=True,
                )
            )

        except Exception:
            logger.exception(
                "TrOCR inference failed"
            )
            raise

        if not decoded_text:
            logger.warning(
                "TrOCR completed but returned no decoded text"
            )
            return ""

        result_text = str(
            decoded_text[0]
        ).strip()

        if not result_text:
            logger.warning(
                "TrOCR returned an empty text result"
            )
            return ""

        logger.info(
            "TrOCR inference completed successfully"
        )

        return result_text


_TROCR_PROVIDER: Optional[
    TrOCRProvider
] = None


def get_trocr_provider() -> TrOCRProvider:
    """
    Return the shared TrOCR provider instance.
    """
    global _TROCR_PROVIDER

    if _TROCR_PROVIDER is None:
        logger.info(
            "Creating shared TrOCR provider instance"
        )

        _TROCR_PROVIDER = (
            TrOCRProvider()
        )

    return _TROCR_PROVIDER