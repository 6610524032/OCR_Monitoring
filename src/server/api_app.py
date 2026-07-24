from flask import Flask
from flask_cors import CORS

from src.server.init_db import ensure_database

from src.server.routes.system_routes import system_bp
from src.server.routes.camera_routes import camera_bp
from src.server.routes.calibration_routes import calibration_bp
from src.server.routes.history_routes import history_bp
from src.server.routes.review_routes import review_bp
from src.server.routes.tag_routes import tag_bp
from src.server.routes.worker_routes import worker_bp


ensure_database()

app = Flask(__name__)
CORS(app)

app.register_blueprint(system_bp)
app.register_blueprint(camera_bp)
app.register_blueprint(calibration_bp)
app.register_blueprint(history_bp)
app.register_blueprint(review_bp)
app.register_blueprint(tag_bp)
app.register_blueprint(worker_bp)

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=False,
        use_reloader=False
    )