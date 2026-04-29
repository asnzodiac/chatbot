import logging
import os
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify

from app.config import Config
from app.telegram import TelegramAPI
from app.handler import handle_update


def create_app() -> Flask:
    app = Flask(__name__)

    # Logging
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("bot")

    # Config + Telegram client
    cfg = Config.load()
    tg = TelegramAPI(cfg.telegram_token)

    # Small worker pool so webhook returns fast (no long blocking inside request)
    executor = ThreadPoolExecutor(max_workers=int(os.getenv("WORKERS", "4")))

    @app.get("/")
    def health():
        return "ok", 200

    @app.post("/webhook")
    def webhook():
        update = request.get_json(force=True, silent=True) or {}
        # Always return quickly; process in background
        executor.submit(_safe_process_update, cfg, tg, update)
        return "ok", 200

    def _safe_process_update(cfg: Config, tg: TelegramAPI, update: dict):
        try:
            handle_update(cfg, tg, update)
        except Exception:
            logger.exception("Unhandled failure while processing update (fail-safe): %s", update)

    @app.route("/setup_webhook", methods=["GET", "POST"])
    def setup_webhook():
        """
        One-time webhook setup helper.
        Optional protection: set SETUP_WEBHOOK_SECRET in env and call with ?secret=...
        """
        secret_env = os.getenv("SETUP_WEBHOOK_SECRET")
        secret_req = request.args.get("secret") or request.form.get("secret")
        if secret_env and secret_env != secret_req:
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        webhook_url = cfg.webhook_url.rstrip("/") + "/webhook"
        ok, resp = tg.set_webhook(webhook_url)
        return jsonify({"ok": ok, "webhook_url": webhook_url, "telegram_response": resp}), (200 if ok else 500)

    return app


app = create_app()

if __name__ == "__main__":
    # Local dev only (Render uses Gunicorn)
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
