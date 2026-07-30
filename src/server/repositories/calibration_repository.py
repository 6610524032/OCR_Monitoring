import math
import sqlite3
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from src.logger import create_logger
from src.server.database import get_connection


logger = create_logger(
    "server.repositories.calibration"
)


DEFAULT_OUTPUT_WIDTH = 900
DEFAULT_OUTPUT_HEIGHT = 700

MAX_OUTPUT_DIMENSION = 10_000
MAX_OUTPUT_PIXELS = 40_000_000
MAX_COORDINATE = 1_000_000.0
MAX_IMAGE_PATH_LENGTH = 1_024

MIN_QUADRILATERAL_AREA = 1.0
GEOMETRY_EPSILON = 1e-6


class CalibrationValidationError(
    ValueError
):
    """
    Raised when calibration input
    is invalid.
    """


def _safe_rollback(
    conn,
) -> None:
    if conn is None:
        return

    try:
        conn.rollback()

    except sqlite3.Error:
        logger.exception(
            (
                "Failed to roll back "
                "calibration transaction"
            )
        )


def _safe_close(
    conn,
) -> None:
    if conn is None:
        return

    try:
        conn.close()

    except sqlite3.Error:
        logger.exception(
            (
                "Failed to close calibration "
                "database connection"
            )
        )


def _validate_image_path(
    value: Any,
) -> str:
    if not isinstance(
        value,
        str,
    ):
        raise CalibrationValidationError(
            "image_path must be a string"
        )

    normalized = (
        value.strip()
        .replace(
            "\\",
            "/",
        )
    )

    if not normalized:
        raise CalibrationValidationError(
            "image_path is required"
        )

    if "\x00" in normalized:
        raise CalibrationValidationError(
            (
                "image_path contains an "
                "invalid character"
            )
        )

    if (
        len(
            normalized
        )
        > MAX_IMAGE_PATH_LENGTH
    ):
        raise CalibrationValidationError(
            "image_path is too long"
        )

    path = PurePosixPath(
        normalized
    )

    if path.is_absolute():
        raise CalibrationValidationError(
            "image_path must be relative"
        )

    if ".." in path.parts:
        raise CalibrationValidationError(
            (
                "image_path cannot leave "
                "the image directory"
            )
        )

    if (
        path.parts
        and ":" in path.parts[0]
    ):
        raise CalibrationValidationError(
            (
                "image_path cannot contain "
                "a drive path"
            )
        )

    return path.as_posix()


def _finite_coordinate(
    value: Any,
    field_name: str,
) -> float:
    if isinstance(
        value,
        bool,
    ):
        raise CalibrationValidationError(
            f"{field_name} must be numeric"
        )

    try:
        number = float(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise CalibrationValidationError(
            f"{field_name} must be numeric"
        ) from error

    if not math.isfinite(
        number
    ):
        raise CalibrationValidationError(
            f"{field_name} must be finite"
        )

    if number < 0:
        raise CalibrationValidationError(
            f"{field_name} cannot be negative"
        )

    if number > MAX_COORDINATE:
        raise CalibrationValidationError(
            f"{field_name} is too large"
        )

    return number


def _positive_dimension(
    value: Any,
    field_name: str,
    default: int,
) -> int:
    if value in (
        None,
        "",
    ):
        return default

    if isinstance(
        value,
        bool,
    ):
        raise CalibrationValidationError(
            f"{field_name} must be an integer"
        )

    if (
        isinstance(
            value,
            float,
        )
        and not value.is_integer()
    ):
        raise CalibrationValidationError(
            f"{field_name} must be an integer"
        )

    try:
        dimension = int(
            value
        )

    except (
        TypeError,
        ValueError,
        OverflowError,
    ) as error:
        raise CalibrationValidationError(
            f"{field_name} must be an integer"
        ) from error

    if dimension <= 0:
        raise CalibrationValidationError(
            (
                f"{field_name} must be "
                "greater than zero"
            )
        )

    if dimension > MAX_OUTPUT_DIMENSION:
        raise CalibrationValidationError(
            (
                f"{field_name} exceeds "
                f"{MAX_OUTPUT_DIMENSION}"
            )
        )

    return dimension


def _cross_product(
    point_a: tuple[
        float,
        float,
    ],
    point_b: tuple[
        float,
        float,
    ],
    point_c: tuple[
        float,
        float,
    ],
) -> float:
    return (
        (
            point_b[0]
            - point_a[0]
        )
        * (
            point_c[1]
            - point_b[1]
        )
        - (
            point_b[1]
            - point_a[1]
        )
        * (
            point_c[0]
            - point_b[0]
        )
    )


def _polygon_area(
    points: list[
        tuple[
            float,
            float,
        ]
    ],
) -> float:
    area_twice = 0.0

    for index, point in enumerate(
        points
    ):
        next_point = points[
            (
                index
                + 1
            )
            % len(
                points
            )
        ]

        area_twice += (
            point[0]
            * next_point[1]
            - next_point[0]
            * point[1]
        )

    return abs(
        area_twice
    ) / 2.0


def _validate_quadrilateral(
    points: list[
        tuple[
            float,
            float,
        ]
    ],
) -> None:
    if (
        len(
            set(
                points
            )
        )
        != 4
    ):
        raise CalibrationValidationError(
            (
                "Calibration points must "
                "be unique"
            )
        )

    area = _polygon_area(
        points
    )

    if area <= MIN_QUADRILATERAL_AREA:
        raise CalibrationValidationError(
            (
                "Calibration points form "
                "an invalid area"
            )
        )

    cross_products = [
        _cross_product(
            points[index],
            points[
                (
                    index
                    + 1
                )
                % 4
            ],
            points[
                (
                    index
                    + 2
                )
                % 4
            ],
        )
        for index in range(
            4
        )
    ]

    if any(
        abs(
            value
        )
        <= GEOMETRY_EPSILON
        for value in cross_products
    ):
        raise CalibrationValidationError(
            (
                "Calibration points cannot "
                "contain collinear edges"
            )
        )

    all_positive = all(
        value > 0
        for value in cross_products
    )

    all_negative = all(
        value < 0
        for value in cross_products
    )

    if not (
        all_positive
        or all_negative
    ):
        raise CalibrationValidationError(
            (
                "Calibration points must be "
                "ordered around a convex shape"
            )
        )


def _validate_payload(
    data: Any,
) -> dict[str, Any]:
    if not isinstance(
        data,
        Mapping,
    ):
        raise CalibrationValidationError(
            (
                "Calibration payload must "
                "be an object"
            )
        )

    image_path = (
        _validate_image_path(
            data.get(
                "image_path"
            )
        )
    )

    raw_points = data.get(
        "points"
    )

    if not isinstance(
        raw_points,
        (
            list,
            tuple,
        ),
    ):
        raise CalibrationValidationError(
            "points must be a list"
        )

    if len(
        raw_points
    ) != 4:
        raise CalibrationValidationError(
            (
                "Exactly four calibration "
                "points are required"
            )
        )

    points = []

    for index, raw_point in enumerate(
        raw_points,
        start=1,
    ):
        if not isinstance(
            raw_point,
            Mapping,
        ):
            raise CalibrationValidationError(
                (
                    f"Point {index} must "
                    "be an object"
                )
            )

        point = (
            _finite_coordinate(
                raw_point.get(
                    "x"
                ),
                (
                    f"points["
                    f"{index - 1}"
                    f"].x"
                ),
            ),
            _finite_coordinate(
                raw_point.get(
                    "y"
                ),
                (
                    f"points["
                    f"{index - 1}"
                    f"].y"
                ),
            ),
        )

        points.append(
            point
        )

    _validate_quadrilateral(
        points
    )

    output_width = (
        _positive_dimension(
            data.get(
                "output_width"
            ),
            "output_width",
            DEFAULT_OUTPUT_WIDTH,
        )
    )

    output_height = (
        _positive_dimension(
            data.get(
                "output_height"
            ),
            "output_height",
            DEFAULT_OUTPUT_HEIGHT,
        )
    )

    if (
        output_width
        * output_height
        > MAX_OUTPUT_PIXELS
    ):
        raise CalibrationValidationError(
            (
                "Calibration output dimensions "
                "are too large"
            )
        )

    return {
        "image_path": image_path,
        "points": points,
        "output_width": (
            output_width
        ),
        "output_height": (
            output_height
        ),
    }


def get_active_calibration():
    """
    Return the newest active calibration,
    or None when no active record exists.
    """
    conn = None

    try:
        conn = get_connection()

        conn.row_factory = (
            sqlite3.Row
        )

        row = conn.execute("""
            SELECT *
            FROM calibration
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        if row is None:
            logger.debug(
                (
                    "No active calibration "
                    "found"
                )
            )

            return None

        calibration = dict(
            row
        )

        if not calibration.get(
            "output_width"
        ):
            calibration[
                "output_width"
            ] = DEFAULT_OUTPUT_WIDTH

        if not calibration.get(
            "output_height"
        ):
            calibration[
                "output_height"
            ] = DEFAULT_OUTPUT_HEIGHT

        logger.debug(
            (
                "Active calibration loaded: "
                "id=%s"
            ),
            calibration.get(
                "id"
            ),
        )

        return calibration

    except sqlite3.Error:
        logger.exception(
            (
                "Failed to load active "
                "calibration"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )


def save_calibration_data(
    data,
):
    """
    Validate and save one active calibration.

    Previous records are deactivated and the
    new record is inserted within one database
    write transaction.
    """
    validated = (
        _validate_payload(
            data
        )
    )

    points = validated[
        "points"
    ]

    conn = None

    try:
        conn = get_connection()

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        conn.execute("""
            UPDATE calibration
            SET
                is_active = 0,
                updated_at = datetime('now')
            WHERE is_active = 1
        """)

        cursor = conn.execute("""
            INSERT INTO calibration (
                image_path,

                p1_x,
                p1_y,
                p2_x,
                p2_y,
                p3_x,
                p3_y,
                p4_x,
                p4_y,

                output_width,
                output_height,

                created_at,
                updated_at,
                is_active
            )
            VALUES (
                ?,
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?,
                datetime('now'),
                datetime('now'),
                1
            )
        """, (
            validated[
                "image_path"
            ],
            points[0][0],
            points[0][1],
            points[1][0],
            points[1][1],
            points[2][0],
            points[2][1],
            points[3][0],
            points[3][1],
            validated[
                "output_width"
            ],
            validated[
                "output_height"
            ],
        ))

        calibration_id = (
            cursor.lastrowid
        )

        conn.commit()

        logger.info(
            (
                "Calibration saved "
                "successfully: id=%s"
            ),
            calibration_id,
        )

        return {
            "id": calibration_id,
            "image_path": validated[
                "image_path"
            ],
            "output_width": validated[
                "output_width"
            ],
            "output_height": validated[
                "output_height"
            ],
        }

    except sqlite3.Error:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Failed to save "
                "calibration"
            )
        )

        raise

    except Exception:
        _safe_rollback(
            conn
        )

        logger.exception(
            (
                "Unexpected error while "
                "saving calibration"
            )
        )

        raise

    finally:
        _safe_close(
            conn
        )