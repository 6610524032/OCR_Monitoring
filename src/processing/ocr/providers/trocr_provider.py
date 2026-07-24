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

from src.server.config import (
    MODEL_CACHE_DIR,
    OCR_MODEL_NAME,
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

    def load_model(
        self,
    ) -> tuple[
        TrOCRProcessor,
        VisionEncoderDecoderModel,
    ]:
        """
        Load the TrOCR processor and model into memory.

        This step loads only model files that already exist
        in the local model cache.
        """
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

        if self.processor is None:
            print(
                "[OCR][TrOCR] "
                "Loading processor..."
            )

            self.processor = (
                TrOCRProcessor.from_pretrained(
                    OCR_MODEL_NAME,
                    cache_dir=str(
                        MODEL_CACHE_DIR
                    ),
                    local_files_only=True,
                    use_fast=False,
                )
            )

            print(
                "[OCR][TrOCR] "
                "Processor loaded"
            )

        if self.model is None:
            print(
                "[OCR][TrOCR] "
                "Loading model..."
            )

            self.model = (
                VisionEncoderDecoderModel
                .from_pretrained(
                    OCR_MODEL_NAME,
                    cache_dir=str(
                        MODEL_CACHE_DIR
                    ),
                    local_files_only=True,
                )
            )

            self.model.eval()

            print(
                "[OCR][TrOCR] "
                "Model loaded"
            )

        return (
            self.processor,
            self.model,
        )

    def read(
        self,
        image: Image.Image,
    ) -> str:
        """
        Read text from a PIL image using TrOCR.
        """
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

        if not decoded_text:
            return ""

        return str(decoded_text[0])


_TROCR_PROVIDER: Optional[
    TrOCRProvider
] = None


def get_trocr_provider() -> TrOCRProvider:
    """
    Return the shared TrOCR provider instance.
    """
    global _TROCR_PROVIDER

    if _TROCR_PROVIDER is None:
        _TROCR_PROVIDER = (
            TrOCRProvider()
        )

    return _TROCR_PROVIDER