"""نقطة الدخول الرئيسية للبوت: إنشاء النسخة، تسجيل المعالجات، وتشغيل الاستطلاع.

مسارات التشغيل:
    python -m phone_status_bot.main        (التشغيل الموصى به)
    python mybot_qwen1.py                  (توافق مع الاسم القديم)

المسؤوليات:
- التحقق من الإعدادات الحرجة قبل أي شيء (config.validate_settings).
- تهيئة السجلات وتنظيف التسجيلات اليتيمة من جلسة سابقة.
- تسجيل إشارات SIGTERM/SIGINT و atexit للإيقاف النظيف.
- حقن نسخة البوت في core.state وتجميع معالجات المجالات (handlers/*).
- تشغيل خيط مراقبة البطارية وحلقة polling مع إعادة محاولة بتراجع أُسّي.
"""

import atexit
import signal
import sys
import threading

import requests
import telebot

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger, setup_logging
from phone_status_bot.handlers import general, media, network, phone, recording, system
from phone_status_bot.services import battery, recording as recording_service
from phone_status_bot.services.sms_gateway import start_sms_server
from phone_status_bot.handlers import general, media, network, phone, ping, recording, system

# ترتيب التسجيل مهم: معالجات الأوامر أولاً، ثم general.handle_unknown
# (المسجَّل داخل register(general)) أخيراً ليلتقط ما تبقى من نصوص غير معروفة.
HANDLER_MODULES = (
    media,
    network,
    ping,
    phone,
    recording,
    system,
    general,
)

# قائمة أوامر Telegram المعروضة في قائمة تلقية الإدخال
BOT_COMMANDS = [
    telebot.types.BotCommand("start", "بدء استخدام البوت وعرض الأوامر"),
    telebot.types.BotCommand("selfie", "تصوير بالكاميرا الأمامية"),
    telebot.types.BotCommand("photo", "تصوير بالكاميرا الخلفية"),
    telebot.types.BotCommand("battery", "معلومات البطارية"),
    telebot.types.BotCommand("network", "معلومات Wi-Fi"),
    telebot.types.BotCommand("cellular", "قوة الشبكة الخلوية وبيانات الهاتف"),
    telebot.types.BotCommand("ping", "فحص اتصال الإنترنت"),
    telebot.types.BotCommand("location", "الموقع الحالي عبر GPS"),
    telebot.types.BotCommand("ip", "عنوان IP المحلي والعام"),
    telebot.types.BotCommand("whois", "معلومات مالك عنوان IP (netname/descr/org/country)"),
    telebot.types.BotCommand("record", "بدء التسجيل الصوتي"),
    telebot.types.BotCommand("stop", "إيقاف التسجيل وإرساله"),
    telebot.types.BotCommand("sms", "إرسال رسالة SMS"),
    telebot.types.BotCommand("uptime", "مدة تشغيل البوت"),
    telebot.types.BotCommand("status", "حالة البوت"),
    telebot.types.BotCommand("admins", "قائمة المسؤولين المعتمدين"),
    telebot.types.BotCommand("help", "إظهار قائمة الأوامر"),
    telebot.types.BotCommand("storage", "مساحة القرص"),
    telebot.types.BotCommand("cpu", "استخدام المعالج والذاكرة"),
    telebot.types.BotCommand("contacts", "قائمة جهات الاتصال"),
    telebot.types.BotCommand("call", "إجراء مكالمة"),
]


def _signal_handler(signum, frame):
    """معالج SIGTERM / SIGINT: إيقاف نظيف عبر حدث SHUTDOWN وإغلاق polling."""
    logger.info("تم استلام إشارة %s، بدء الإيقاف النظيف...", signum)
    state.SHUTDOWN.set()
    try:
        if state.bot is not None:
            state.bot.stop_polling()
    except Exception:
        pass


def _register_commands(bot):
    """تسجيل قائمة الأوامر لدى Telegram (غير حرج — يُسجَّل الفشل فقط)."""
    try:
        bot.set_my_commands(BOT_COMMANDS)
    except Exception as e:
        logger.warning("تعذر تسجيل قائمة الأوامر: %s", e)


def _poll_with_backoff(bot):
    """حلقة infinity_polling مع تراجع أُسّي عند أخطاء الاتصال حتى حدث الإيقاف."""
    backoff = 5
    while not state.SHUTDOWN.is_set():
        try:
            # skip_pending مضبوط على False افتراضياً حتى لا تُتجاهل أوامر معلّقة
            bot.infinity_polling(
                timeout=30,
                long_polling_timeout=20,
                skip_pending=False,
            )
            backoff = 5
        except KeyboardInterrupt:
            break
        except requests.exceptions.ReadTimeout:
            logger.warning("انتهت مهلة الاتصال، سيتم إعادة المحاولة.")
            state.SHUTDOWN.wait(min(backoff, 60))
        except requests.exceptions.RequestException as e:
            logger.exception("خطأ اتصال: %s", e)
            state.SHUTDOWN.wait(min(backoff, 60))
            backoff = min(backoff * 2, 300)
        except Exception as e:
            logger.exception("خطأ غير متوقع في البوت: %s", e)
            state.SHUTDOWN.wait(min(backoff, 60))
            backoff = min(backoff * 2, 300)


def run():
    """تهيئة البوت وتشغيله حتى الإيقاف. ترجع رمز خروج."""
    # 1) التحقق من الإعدادات الحرجة (ترفع SystemExit برسالة واضحة)
    config.validate_settings()

    # 2) السجلات (ملف دوّار + وحدة تحكم) — logger الحزمة هو المصدر الوحيد
    setup_logging()

    # 3) تنظيف التسجيلات اليتيمة من جلسة سابقة (حتى بعد kill -9)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    recording_service.cleanup_orphan_recordings()

    # 4) إنشاء نسخة البوت وحقنها في الحالة المشتركة
    bot = telebot.TeleBot(config.BOT_TOKEN)
    state.init_bot(bot)
    # تشغيل مستقبل SMS داخل خيط خلفي
    start_sms_server(bot, config.ADMIN_IDS)

    # 5) تسجيل معالجات المجالات
    for module in HANDLER_MODULES:
        module.register(bot)

    # 6) قوائم انتظار التنظيف والإشارات
    atexit.register(recording_service.cleanup_recording)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    logger.info("%s بدأ التشغيل...", config.APP_NAME)
    print("البوت يعمل الآن...")

    # 7) قائمة الأوامر + خيط مراقبة البطارية
    _register_commands(bot)
    monitor_thread = threading.Thread(target=battery.battery_monitor, daemon=True)
    monitor_thread.start()

    # 8) حلقة الاستطلاع الرئيسية
    _poll_with_backoff(bot)

    # 9) إيقاف نظيف
    state.SHUTDOWN.set()
    recording_service.cleanup_recording()
    logger.info("تم إيقاف البوت بشكل نظيف.")
    return 0


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
