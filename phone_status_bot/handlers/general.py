"""معالجات المعلومات العامة عن البوت: /start /help /uptime /status /admins + معالج الرسائل غير المعروفة."""

import datetime
import time

from phone_status_bot.core import config, state
from phone_status_bot.core.html_utils import send_html_reply
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import admin_only

# تُضبط من main.run() عند بدء التشغيل (لتوحيد مصدر وقت البداية)
BOT_START_TIME = datetime.datetime.now()

HELP_TEXT = (
    "أهلاً بك! الأوامر المتاحة:\n\n"
    "/selfie - تصوير بالكاميرا الأمامية\n"
    "/photo - تصوير بالكاميرا الخلفية\n"
    "/battery - معلومات البطارية\n"
    "/network - معلومات Wi-Fi\n"
    "/cellular - قوة الشبكة الخلوية وبيانات الهاتف\n"
    "/location - الموقع الحالي عبر GPS\n"
    "/ip - عنوان IP المحلي والعام\n"
    "/whois ip - معلومات مالك عنوان IP (netname/descr/org/country)\n"
    "/record - بدأ التسجيل الصوتي\n"
    "/stop - إيقاف التسجيل وإرساله\n"
    "/sms رقم نص - إرسال رسالة SMS\n"
    "/uptime - مدة تشغيل البوت\n"
    "/status - حالة البوت\n"
    "/admins - قائمة المسؤولين المعتمدين\n"
    "/help - إظهار هذه الرسالة\n"
    "/storage - مساحة القرص\n"
    "/cpu - استخدام المعالج والذاكرة\n"
    "/contacts - قائمة جهات الاتصال\n"
    "/call رقم - إجراء مكالمة\n"
    "\n🔔 ملاحظة: تنبيهات البطارية تعمل تلقائياً عند 60%, 50%, 40%, 30%"
)


def format_uptime(start_time, now=None):
    """تنسيق مدة التشغيل نصياً بالعربية."""
    delta = (now or datetime.datetime.now()) - start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days} يوم،")
    parts.append(f"{hours} ساعة، {minutes} دقيقة، {seconds} ثانية")
    return " ".join(parts)


def register(bot):
    state.init_bot(bot)

    @bot.message_handler(commands=["start", "help"])
    @admin_only
    def send_welcome(message):
        bot.reply_to(message, HELP_TEXT)
        logger.info("تم عرض قائمة الأوامر للمستخدم %s", message.from_user.id)

    @bot.message_handler(commands=["uptime"])
    @admin_only
    def get_uptime(message):
        uptime_str = format_uptime(BOT_START_TIME)
        send_html_reply(bot, message, f"⏳ <b>مدة تشغيل البوت:</b>\n{uptime_str}")
        logger.info("تم طلب مدة التشغيل من المستخدم %s", message.from_user.id)

    @bot.message_handler(commands=["status"])
    @admin_only
    def bot_status(message):
        status = (
            "🟢 حالة البوت: يعمل\n"
            f"👤 المسؤولون: {', '.join(map(str, sorted(config.ADMIN_IDS)))}\n"
            f"📄 سجل التشغيل: {config.LOG_FILE}\n"
            f"🕐 الوقت: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        bot.reply_to(message, status)
        logger.info("تم طلب حالة البوت من المستخدم %s", message.from_user.id)

    @bot.message_handler(commands=["admins"])
    @admin_only
    def list_admins(message):
        if not config.ADMIN_IDS:
            msg = "⚠️ لا يوجد مسؤولون معتمدون! تأكد من ضبط متغير ADMIN_ID."
        else:
            admins_list = "\n".join(f"• <code>{aid}</code>" for aid in sorted(config.ADMIN_IDS))
            msg = (
                f"👥 <b>المسؤولون المعتمدون ({len(config.ADMIN_IDS)}):</b>\n{admins_list}\n\n"
                "➕ للإضافة: عدّل ADMIN_ID في ~/.bashrc أو .env بفواصل بين المعرفات،\n"
                "ثم نفّذ: source ~/.bashrc وأعد تشغيل البوت."
            )
        send_html_reply(bot, message, msg)
        logger.info("تم عرض قائمة المسؤولين للمستخدم %s", message.from_user.id)

    # ================== الرسائل غير المعروفة ==================
    # يُسجَّل أخيراً ليلتقط فقط ما لم تلتقطه معالجات الأوامر الأخرى
    @bot.message_handler(content_types=["text"])
    @admin_only
    def handle_unknown(message):
        if message.text and message.text.startswith("/"):
            uid = message.from_user.id if message.from_user else "unknown"
            logger.info("أمر غير معروف: %s من المستخدم %s", message.text, uid)
            bot.reply_to(message, "❓ أمر غير معروف. أرسل /help لعرض القائمة.")
        # الرسائل النصية العادية تُتجاهل (البوت أوامري فقط)
