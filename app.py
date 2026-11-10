import os
from flask import Flask
from routes.api import api_bp
from routes.main import main_bp
import market_data
from portfolio_engine import prefetch_universe

def create_app():
    app = Flask(__name__)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    market_data.start_prefetch(prefetch_universe())   # warms the daily price cache in the background
    return app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
