import logging
import threading

from flask import Flask, request, jsonify

logger = logging.getLogger("telegram_bot")

SECRET_KEY = "my_sms_secret_2026"
HOST = "127.0.0.1"
PORT = 8765

app = Flask(__name__)


def register_sms_routes(bot, admin_ids):

    @app.route("/sms", methods=["POST"])
    def receive_sms():

        data = request.get_json(silent=True) or request.form

        if data.get("key") != SECRET_KEY:
            return jsonify({"error": "Unauthorized"}), 401

        sender = str(data.get("sender", "Unknown")).strip()
        message = str(data.get("message", "")).strip()

        if not message:
            return jsonify({"error": "Empty message"}), 400

        text = (
            "📩 رسالة SMS جديدة\n\n"
            f"👤 المرسل: {sender}\n"
            f"📝 الرسالة:\n{message}"
        )

        sent = 0

        for admin_id in admin_ids:
            try:
                bot.send_message(admin_id, text)
                sent += 1
            except Exception:
                logger.exception(
                    "Failed to send SMS notification to admin %s",
                    admin_id
                )

        if sent == 0:
            return jsonify({
                "error": "Could not deliver message to any admin"
            }), 502

        logger.info(
            "SMS from %s delivered to %s admin(s)",
            sender,
            sent
        )

        return jsonify({
            "status": "received",
            "telegram": "sent",
            "recipients": sent
        }), 200


def start_sms_server(bot, admin_ids):

    register_sms_routes(bot, admin_ids)

    thread = threading.Thread(
        target=lambda: app.run(
            host=HOST,
            port=PORT,
            debug=False,
            use_reloader=False,
            threaded=True
        ),
        name="SMS-Gateway",
        daemon=True
    )

    thread.start()

    logger.info(
        "SMS Gateway started on %s:%s",
        HOST,
        PORT
    )

    return thread

