from flask import Flask
from flask_cors import CORS

from src.logger import create_logger
from src.server.init_db import ensure_database

from src.server.routes.system_routes import system_bp
from src.server.routes.camera_routes import camera_bp
from src.server.routes.calibration_routes import calibration_bp
from src.server.routes.history_routes import history_bp
from src.server.routes.review_routes import review_bp
from src.server.routes.tag_routes import tag_bp
from src.server.routes.worker_routes import worker_bp


logger = create_logger(
    "server.api_app"
)


def create_app() -> Flask:
    """
    Create and configure the API server application.
    """
    logger.info(
        "Starting API server initialization"
    )

    try:
        ensure_database()

    except Exception:
        logger.exception(
            "API server database initialization failed"
        )
        raise

    app = Flask(__name__)
    CORS(app)

    app.register_blueprint(system_bp)
    app.register_blueprint(camera_bp)
    app.register_blueprint(calibration_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(tag_bp)
    app.register_blueprint(worker_bp)

    logger.info(
        "API server initialization completed"
    )

    return app


app = create_app()


if __name__ == "__main__":
    logger.info(
        "API server is starting on 0.0.0.0:5001"
    )

    try:
        app.run(
            host="0.0.0.0",
            port=5001,
            debug=False,
            use_reloader=False,
        )

    except Exception:
        logger.exception(
            "API server stopped unexpectedly"
        )
        raise