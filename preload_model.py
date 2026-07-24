from transformers import (
    TrOCRProcessor,
    VisionEncoderDecoderModel,
)

from src.server.config import (
    MODEL_CACHE_DIR,
    OCR_MODEL_NAME,
)


def main() -> None:
    MODEL_CACHE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("Preloading OCR model...")
    print(f"Model: {OCR_MODEL_NAME}")
    print(
        f"Cache directory: "
        f"{MODEL_CACHE_DIR.resolve()}"
    )

    print("Loading processor...")

    TrOCRProcessor.from_pretrained(
        OCR_MODEL_NAME,
        cache_dir=str(MODEL_CACHE_DIR),
        use_fast=False,
    )

    print("Loading model...")

    VisionEncoderDecoderModel.from_pretrained(
        OCR_MODEL_NAME,
        cache_dir=str(MODEL_CACHE_DIR),
    )

    print("OCR model preloaded successfully.")


if __name__ == "__main__":
    main()