import os
from pathlib import Path

from transformers import TrOCRProcessor, VisionEncoderDecoderModel


MODEL_NAME = os.getenv(
    "TROCR_MODEL_NAME",
    "microsoft/trocr-base-printed",
)


def get_cache_dir() -> Path:
    project_root = Path(__file__).resolve().parent

    cache_dir_value = os.getenv("MODEL_CACHE_DIR")

    if cache_dir_value:
        cache_dir = Path(cache_dir_value)
    else:
        cache_dir = project_root / "model_cache" / "huggingface"

    cache_dir.mkdir(parents=True, exist_ok=True)

    return cache_dir.resolve()


def main() -> None:
    cache_dir = get_cache_dir()

    print("Preloading TrOCR model...")
    print(f"Model: {MODEL_NAME}")
    print(f"Cache directory: {cache_dir}")

    print("Loading processor...")
    TrOCRProcessor.from_pretrained(
        MODEL_NAME,
        cache_dir=str(cache_dir),
        use_fast=False,
    )

    print("Loading model...")
    VisionEncoderDecoderModel.from_pretrained(
        MODEL_NAME,
        cache_dir=str(cache_dir),
    )

    print("TrOCR model preloaded successfully.")


if __name__ == "__main__":
    main()