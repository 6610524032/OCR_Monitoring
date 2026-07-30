import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from src.logger import create_logger
from src.server.config import (
    INCOMING_DIR,
    RAW_IMAGES_DIR,
)


logger = create_logger(
    "processing.capture"
)


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
}

FILE_STABILITY_CHECKS = 3
FILE_STABILITY_DELAY_SECONDS = 0.4


def _failure_result(
    stage: str,
    message: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "stage": stage,
        "message": message,
    }


def _safe_remove_file(
    file_path: Path | None,
) -> None:
    if file_path is None:
        return

    try:
        if file_path.exists():
            file_path.unlink()

    except OSError:
        logger.exception(
            (
                "Cannot remove temporary "
                "capture file: %s"
            ),
            file_path,
        )


def _prepare_directories() -> bool:
    try:
        INCOMING_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        RAW_IMAGES_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        return True

    except OSError:
        logger.exception(
            (
                "Cannot prepare image "
                "directories"
            )
        )

        return False


def _get_file_stat(
    file_path: Path,
):
    try:
        return file_path.stat()

    except (
        FileNotFoundError,
        OSError,
    ):
        return None


def _get_incoming_images(
) -> list[tuple[Path, float]]:
    image_files = []

    try:
        entries = list(
            INCOMING_DIR.iterdir()
        )

    except OSError:
        logger.exception(
            (
                "Cannot read incoming "
                "image directory"
            )
        )

        return []

    for file_path in entries:
        try:
            if not file_path.is_file():
                continue

            if (
                file_path.suffix.lower()
                not in IMAGE_EXTENSIONS
            ):
                continue

            file_stat = (
                _get_file_stat(
                    file_path
                )
            )

            if file_stat is None:
                continue

            if file_stat.st_size <= 0:
                continue

            image_files.append(
                (
                    file_path,
                    file_stat.st_mtime,
                )
            )

        except OSError:
            logger.warning(
                (
                    "Cannot inspect incoming "
                    "file: %s"
                ),
                file_path,
            )

    image_files.sort(
        key=lambda item: (
            item[1],
            item[0].name.lower(),
        )
    )

    return image_files


def _is_file_stable(
    file_path: Path,
) -> bool:
    """
    Confirm that the incoming file is no longer
    changing before moving it into raw_images.
    """
    previous_size = None
    previous_modified_ns = None

    for check_index in range(
        FILE_STABILITY_CHECKS
    ):
        file_stat = (
            _get_file_stat(
                file_path
            )
        )

        if file_stat is None:
            return False

        if file_stat.st_size <= 0:
            return False

        current_size = (
            file_stat.st_size
        )

        current_modified_ns = (
            file_stat.st_mtime_ns
        )

        if (
            previous_size is not None
            and current_size
            == previous_size
            and current_modified_ns
            == previous_modified_ns
        ):
            return True

        previous_size = (
            current_size
        )

        previous_modified_ns = (
            current_modified_ns
        )

        if (
            check_index
            < FILE_STABILITY_CHECKS - 1
        ):
            time.sleep(
                FILE_STABILITY_DELAY_SECONDS
            )

    return False


def _get_file_modified_time(
    file_path: Path | None,
) -> datetime:
    if file_path is not None:
        file_stat = (
            _get_file_stat(
                file_path
            )
        )

        if file_stat is not None:
            try:
                local_timezone = (
                    datetime.now()
                    .astimezone()
                    .tzinfo
                )

                return datetime.fromtimestamp(
                    file_stat.st_mtime,
                    tz=local_timezone,
                )

            except (
                OSError,
                OverflowError,
                ValueError,
            ):
                logger.warning(
                    (
                        "Cannot use file modified "
                        "time for capture: %s"
                    ),
                    file_path,
                )

    return (
        datetime.now()
        .astimezone()
    )


def parse_capture_time_from_filename(
    filename,
    fallback_path: Path | None = None,
):
    filename_stem = (
        Path(
            str(filename)
        ).stem
    )

    timestamp_text = (
        filename_stem.replace(
            "_rtsp",
            "",
        )
    )

    try:
        parsed_time = (
            datetime.strptime(
                timestamp_text,
                "%Y-%m-%d_%H-%M-%S_%f",
            )
        )

        local_timezone = (
            datetime.now()
            .astimezone()
            .tzinfo
        )

        return parsed_time.replace(
            tzinfo=local_timezone
        )

    except ValueError:
        captured_at = (
            _get_file_modified_time(
                fallback_path
            )
        )

        logger.warning(
            (
                "Cannot parse capture time "
                "from filename: %s. "
                "Using file modified time: %s"
            ),
            filename,
            captured_at.isoformat(),
        )

        return captured_at


def _build_unique_target_path(
    target_folder: Path,
    filename: str,
) -> Path:
    original_path = (
        target_folder
        / filename
    )

    if not original_path.exists():
        return original_path

    source_path = Path(
        filename
    )

    stem = source_path.stem
    suffix = source_path.suffix

    for number in range(
        1,
        10001,
    ):
        candidate = (
            target_folder
            / f"{stem}_{number}{suffix}"
        )

        if not candidate.exists():
            logger.warning(
                (
                    "Capture destination already "
                    "exists; using new filename: %s"
                ),
                candidate.name,
            )

            return candidate

    raise FileExistsError(
        (
            "Cannot generate a unique "
            "capture filename"
        )
    )


def _move_image_safely(
    source_path: Path,
    target_path: Path,
) -> None:
    temporary_path = (
        target_path.parent
        / (
            f".{target_path.name}"
            ".moving"
        )
    )

    _safe_remove_file(
        temporary_path
    )

    try:
        shutil.move(
            str(
                source_path
            ),
            str(
                temporary_path
            ),
        )

        temporary_stat = (
            _get_file_stat(
                temporary_path
            )
        )

        if (
            temporary_stat is None
            or temporary_stat.st_size <= 0
        ):
            raise OSError(
                (
                    "Moved image file is "
                    "missing or empty"
                )
            )

        temporary_path.replace(
            target_path
        )

    except Exception:
        # หาก Move ไปยังไฟล์ชั่วคราวสำเร็จแล้ว
        # แต่เปลี่ยนชื่อสุดท้ายไม่สำเร็จ พยายาม
        # คืนไฟล์กลับไปยัง Incoming
        if (
            temporary_path.exists()
            and not source_path.exists()
        ):
            try:
                temporary_path.replace(
                    source_path
                )

            except OSError:
                logger.exception(
                    (
                        "Cannot restore incoming "
                        "image after move failure: %s"
                    ),
                    source_path,
                )

        raise

    finally:
        _safe_remove_file(
            temporary_path
        )


def capture_image():
    """
    Move the oldest complete incoming image into
    the date-based raw_images directory.

    Returns None when no complete image is ready.
    """
    if not _prepare_directories():
        return None

    image_files = (
        _get_incoming_images()
    )

    if not image_files:
        return None

    image_file = (
        image_files[0][0]
    )

    if not _is_file_stable(
        image_file
    ):
        logger.debug(
            (
                "Incoming image is not ready "
                "for processing: %s"
            ),
            image_file.name,
        )

        return None

    logger.info(
        "Found incoming image: %s",
        image_file.name,
    )

    captured_at = (
        parse_capture_time_from_filename(
            filename=image_file.name,
            fallback_path=image_file,
        )
    )

    capture_timestamp = int(
        captured_at.timestamp()
    )

    date_folder = (
        captured_at.strftime(
            "%Y-%m-%d"
        )
    )

    target_folder = (
        RAW_IMAGES_DIR
        / date_folder
    )

    try:
        target_folder.mkdir(
            parents=True,
            exist_ok=True,
        )

    except OSError:
        logger.exception(
            (
                "Cannot create raw image "
                "date directory: %s"
            ),
            target_folder,
        )

        return None

    try:
        target_path = (
            _build_unique_target_path(
                target_folder=target_folder,
                filename=image_file.name,
            )
        )

    except (
        OSError,
        ValueError,
    ):
        logger.exception(
            (
                "Cannot prepare destination "
                "for incoming image: %s"
            ),
            image_file,
        )

        return None

    try:
        _move_image_safely(
            source_path=image_file,
            target_path=target_path,
        )

    except Exception:
        logger.exception(
            (
                "Cannot move image to "
                "raw_images: %s"
            ),
            image_file,
        )

        return None

    target_stat = (
        _get_file_stat(
            target_path
        )
    )

    if (
        target_stat is None
        or target_stat.st_size <= 0
    ):
        logger.error(
            (
                "Moved image is missing "
                "or empty: %s"
            ),
            target_path,
        )

        return None

    logger.info(
        (
            "Image moved successfully: "
            "source=%s destination=%s"
        ),
        image_file,
        target_path,
    )

    return {
        "image_path": str(
            target_path
        ),
        "captured_at": (
            captured_at.isoformat()
        ),
        "capture_timestamp": (
            capture_timestamp
        ),
    }