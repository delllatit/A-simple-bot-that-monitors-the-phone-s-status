import html
import hmac
import logging
import re
import secrets
import threading
import time
from collections import deque

from flask import Flask, request, jsonify

from phone_status_bot.core import config

logger = logging.getLogger("telegram_bot")

# حد عدد الطلبات (rate limiting) — حتى على loopback، أي عملية محلية قادرة على
# إرسال رسائل SMS قد تُغرق البوت وتعلّق حساب Telegram (حد 40 رسالة/دقيقة).
RATE_WINDOW_SECONDS = int(getattr(config, "SMS_RATE_WINDOW", 60))
RATE_MAX_REQUESTS = int(getattr(config, "SMS_RATE_MAX", 10))
# أقصى طول لنص الرسالة/المرسل قبل الاقتطاع — يمنع رسائل ضخمة وDoS بسيط
MAX_FIELD_LEN = 3000

_rate_lock = threading.Lock()
_rate_hits = deque()  # طوابع زمنية للطلبات المقبولة داخل النافذة


def _rate_limited():
    """يعيد True إذا تجاوزت الطلبات الحد المسموح داخل النافذة الزمنية."""
    now = time.monotonic()
    with _rate_lock:
        while _rate_hits and now - _rate_hits[0] > RATE_WINDOW_SECONDS:
            _rate_hits.popleft()
        if len(_rate_hits) >= RATE_MAX_REQUESTS:
            return True
        _rate_hits.append(now)
        return False


_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9.\-_:]{1,253}$")


def _safe_host(value):
    """يتحقق أن القيمة اسم مضيف/IPv4 صالح فقط — يمنع حقن وسوم Markdown/HTML
    أو أوامر عبر وسيط host في /ping."""
    value = (value or "").strip()
    if not _HOSTNAME_RE.match(value):
        return None
    return value

# المفتاح السري يُقرأ من البيئة/ملف .env (لا يُخزَّن داخل الكود المصدري).
# لماذا؟ لأن المشروع نموذج مفتوح يأخذه كل مستخدم لينشئ بوتاً خاصاً به على
# هاتفه — أي قيمة ثابتة في الكود تصبح معروفة للجميع فور نشر المستودع.
# إن لم يضبط المستخدم SMS_SECRET في .env، يُولَّد مفتاح عشوائي فريد عند
# كل تشغيل ويُطبع في السجل لنسخه إلى سكربت termux-sms-list المحلي.
SECRET_KEY = None  # تُضبط عبر init_secret() قبل بدء الخادم
HOST = "127.0.0.1"  # loopback فقط — لا وصول من الشبكة الخارجية
PORT = getattr(config, "SMS_GATEWAY_PORT", 8765)


def init_secret():
    """يُهيّئ المفتاح السري للبوابة: من .env أو توليد عشوائي فريد."""
    global SECRET_KEY
    configured = getattr(config, "SMS_SECRET", "") or ""
    if configured:
        SECRET_KEY = configured
        logger.info("SMS Gateway: تم استخدام المفتاح السري من ملف .env")
    else:
        SECRET_KEY = secrets.token_hex(16)
        logger.warning(
            "SMS Gateway: لم يتم ضبط SMS_SECRET في .env — تم توليد مفتاح "
            "عشوائي لهذا التشغيل: %s\n"
            "أضِف هذا القيمة إلى سكربت Termux المحلي، أو اضبط SMS_SECRET "
            "دائماً في .env لتثبيته.",
            SECRET_KEY,
        )
    return SECRET_KEY

app = Flask(__name__)


def register_sms_routes(bot, admin_ids):

    @app.route("/sms", methods=["POST"])
    def receive_sms():

        # حد الطلبات قبل أي معالجة — يمنع الإغراق المحلي وتعليق حساب Telegram
        if _rate_limited():
            logger.warning(
                "SMS Gateway: تجاوز حد الطلبات (%s طلب/%s ثانية) — رفض الطلب",
                RATE_MAX_REQUESTS,
                RATE_WINDOW_SECONDS,
            )
            return jsonify({"error": "Rate limit exceeded"}), 429

        data = request.get_json(silent=True) or request.form

        provided = str(data.get("key", ""))
        # مقارنة آمنة زمنياً لمنع هجمات timing side-channel
        if not SECRET_KEY or not hmac.compare_digest(provided, SECRET_KEY):
            logger.warning("SMS Gateway: محاولة وصول بمفتاح غير صحيح")
            return jsonify({"error": "Unauthorized"}), 401

        sender = str(data.get("sender", "Unknown")).strip()[:200]
        message = str(data.get("message", "")).strip()[:MAX_FIELD_LEN]

        if not message:
            return jsonify({"error": "Empty message"}), 400

        # تهريب HTML — بدون هذا يستطيع مصدر SMS (أو أي عملية محلية صالحة
        # بالمفتاح) حقن وسوم <b>/<a href=...> في تنبيهات المسؤولين.
        text = (
            "📩 رسالة SMS جديدة\n\n"
            f"👤 المرسل: {html.escape(sender)}\n"
            f"📝 الرسالة:\n{html.escape(message)}"
        )

        sent = 0

        for admin_id in admin_ids:
            try:
                bot.send_message(admin_id, text, parse_mode="HTML")
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

    init_secret()
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

