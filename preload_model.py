import os
from pathlib import Path


MODEL_NAME = "microsoft/trocr-base-printed"

MODEL_CACHE_DIR = Path(
    os.environ.get(
        "MODEL_CACHE_DIR",
        "/app/model_cache/huggingface"
    )
)

MODEL_CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)

os.environ["HF_HOME"] = str(MODEL_CACHE_DIR)
os.environ["HUGGINGFACE_HUB_CACHE"] = str(MODEL_CACHE_DIR)


from transformers import (
    TrOCRProcessor,
    VisionEncoderDecoderModel
)


def preload_model():
    print("Preloading TrOCR model...")
    print("Model:", MODEL_NAME)
    print("Cache directory:", MODEL_CACHE_DIR)

    print("Loading processor...")

    TrOCRProcessor.from_pretrained(
        MODEL_NAME,
        cache_dir=str(MODEL_CACHE_DIR),
        use_fast=False
    )

    print("Loading model...")

    VisionEncoderDecoderModel.from_pretrained(
        MODEL_NAME,
        cache_dir=str(MODEL_CACHE_DIR)
    )

    print("TrOCR model preloaded successfully.")


if __name__ == "__main__":
    preload_model()