import os
import re

import cv2
from PIL import Image

from app.server.config import (
    CALIBRATED_IMAGES_DIR,
    MODEL_CACHE_DIR
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

from app.server.config import CALIBRATED_IMAGES_DIR


TROCR_PROCESSOR = None
TROCR_MODEL = None


def load_model():
    global TROCR_PROCESSOR, TROCR_MODEL

    if TROCR_PROCESSOR is None:
        TROCR_PROCESSOR = TrOCRProcessor.from_pretrained(
            "microsoft/trocr-base-printed",
            cache_dir=str(MODEL_CACHE_DIR),
            local_files_only=True,
            use_fast=False
        )

    if TROCR_MODEL is None:
        TROCR_MODEL = VisionEncoderDecoderModel.from_pretrained(
            "microsoft/trocr-base-printed",
            cache_dir=str(MODEL_CACHE_DIR),
            local_files_only=True
        )

    return TROCR_PROCESSOR, TROCR_MODEL


def normalize_text(text):
    text = str(text).strip().replace(" ", "")
    text = text.replace(",", ".")
    text = text.replace("O", "0").replace("o", "0")

    return text


def extract_value(text):
    raw_text = str(text).strip()

    if not re.search(r"\d", raw_text):
        return ""

    text = normalize_text(raw_text)

    patterns = [
        r"\d+(?::\d+)+",
        r"\d+(?:[/-]\d+)+",
        r"\d+\.\d+",
        r"\d+"
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return match.group(0)

    return ""


def prepare_crop(crop):
    if crop is None or crop.size == 0:
        return None

    crop = cv2.copyMakeBorder(
        crop,
        12,
        12,
        12,
        12,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255)
    )

    crop = cv2.resize(
        crop,
        None,
        fx=4,
        fy=4,
        interpolation=cv2.INTER_CUBIC
    )

    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)

    return Image.fromarray(rgb)


def crop_image(image, x1, y1, x2, y2):
    image_h, image_w = image.shape[:2]

    x1 = int(round(float(x1)))
    y1 = int(round(float(y1)))
    x2 = int(round(float(x2)))
    y2 = int(round(float(y2)))

    x1, x2 = sorted([x1, x2])
    y1, y2 = sorted([y1, y2])

    x1 = max(0, min(image_w, x1))
    x2 = max(0, min(image_w, x2))
    y1 = max(0, min(image_h, y1))
    y2 = max(0, min(image_h, y2))

    if x2 <= x1 or y2 <= y1:
        return None

    return image[y1:y2, x1:x2]


def crop_by_roi(image, tag):
    return crop_image(
        image=image,
        x1=tag["roi_x1"],
        y1=tag["roi_y1"],
        x2=tag["roi_x2"],
        y2=tag["roi_y2"]
    )


def read_crop_with_trocr(crop):
    if crop is None or crop.size == 0:
        return {
            "ok": False,
            "value": "",
            "raw_text": "",
            "message": "Empty crop"
        }

    try:
        pil_image = prepare_crop(crop)

        if pil_image is None:
            return {
                "ok": False,
                "value": "",
                "raw_text": "",
                "message": "Cannot prepare crop"
            }

        processor, model = load_model()

        pixel_values = processor(
            images=pil_image,
            return_tensors="pt"
        ).pixel_values

        generated_ids = model.generate(
            pixel_values,
            max_length=40
        )

        raw_text = processor.batch_decode(
            generated_ids,
            skip_special_tokens=True
        )[0]

        value = extract_value(raw_text)

        return {
            "ok": True,
            "value": value,
            "raw_text": raw_text,
            "message": "success"
        }

    except Exception as error:
        return {
            "ok": False,
            "value": "",
            "raw_text": "",
            "message": str(error)
        }


def read_manual_roi(image_name, x1, y1, x2, y2):
    image_path = CALIBRATED_IMAGES_DIR / image_name

    if not image_path.exists():
        return {
            "ok": False,
            "message": "Image not found"
        }

    image = cv2.imread(str(image_path))

    if image is None:
        return {
            "ok": False,
            "message": "Cannot read image"
        }

    crop = crop_image(
        image=image,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2
    )

    result = read_crop_with_trocr(crop)

    if not result.get("ok"):
        return {
            "ok": False,
            "message": result.get("message", "TrOCR failed")
        }

    return {
        "ok": True,
        "text": result.get("value", ""),
        "raw_text": result.get("raw_text", "")
    }