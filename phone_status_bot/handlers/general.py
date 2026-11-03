# phone_status_bot/handlers/general.py
"""معالجات المعلومات العامة عن البوت: /start /help /uptime /status /admins + معالج الرسائل غير المعروفة."""

import datetime
import time

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import admin_only

# تُضبط عند تحميل الوحدة (يمكن نقلها إلى main.run() لاحقاً إن أردت)
BOT_START_TIME = datetime.datetime.now()

HELP_TEXT = (
    "👋 <b>أهلاً بك في بوت حالة الهاتف</b>\n"
    "<i>البوت أوامري فقط — أرسل الأمر مباشرة.</i>\n"
    "\n"
    "📸 <b>الكاميرا والوسائط</b>\n"
    "  <code>/selfie</code> — تصوير بالكاميرا الأمامية\n"
    "  <code>/photo</code> — تصوير بالكاميرا الخلفية\n"
    " <code>/screenshot</code> — تصوير الشاشة\n"
    "\n"
    "📶 <b>الشبكة والاتصال</b>\n"
    "  <code>/network</code> — معلومات Wi-Fi\n"
    "  <code>/cellular</code> — قوة الشبكة الخلوية وبيانات الهاتف\n"
    "  <code>/hotspot</code> — تشغيل/إيقاف نقطة الاتصال (on/off)\n"
    "  <code>/bluetooth</code> — تشغيل/إيقاف البلوتوث (on/off)\n"
    "  <code>/ping [host]</code> — فحص الإنترنت (ICMP + TCP + DNS)\n"
    "  <code>/ip</code> — عنوان IP المحلي والعام\n"
    "  <code>/whois ip</code> — معلومات مالك عنوان IP\n"
    "\n"
    "📍 <b>الموقع</b>\n"
    "  <code>/location</code> — الموقع الحالي عبر GPS\n"
    "\n"
    "🎙️ <b>الصوت والتسجيل</b>\n"
    "  <code>/record</code> — بدء التسجيل الصوتي\n"
    "  <code>/stop</code> — إيقاف التسجيل وإرساله\n"
    "\n"
    "💬 <b>الرسائل والمكالمات</b>\n"
    "  <code>/sms رقم نص</code> — إرسال رسالة SMS\n"
    "  <code>/call رقم</code> — إجراء مكالمة\n"
    "  <code>/clipboard نص</code> — حفظ النص في الحافظة\n"
    "  <code>/contacts</code> — قائمة جهات الاتصال\n"
    "\n"
    "📱 <b>الجهاز</b>\n"
    "  <code>/battery</code> — معلومات البطارية\n"
    "  <code>/storage</code> — مساحة القرص\n"
    "  <code>/cpu</code> — استخدام المعالج والذاكرة\n"
    "  <code>/capabilities</code> — توافقية الجهاز\n"
    "\n"
    "ℹ️ <b>معلومات البوت</b>\n"
    "  <code>/uptime</code> — مدة تشغيل البوت\n"
    "  <code>/status</code> — حالة البوت\n"
    "  <code>/admins</code> — قائمة المسؤولين\n"
    "  <code>/help</code> — إظهار هذه الرسالة\n"
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
        bot.reply_to(message, HELP_TEXT, parse_mode="HTML",
                     disable_web_page_preview=True)
        logger.info("تم عرض قائمة الأوامر للمستخدم %s", message.from_user.id)

    @bot.message_handler(commands=["uptime"])
    @admin_only
    def get_uptime(message):
        uptime_str = format_uptime(BOT_START_TIME)
        bot.reply_to(message, f"⏳ <b>مدة تشغيل البوت:</b>\n{uptime_str}", parse_mode="HTML")
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
        bot.reply_to(message, msg, parse_mode="HTML")
        logger.info("تم عرض قائمة المسؤولين للمستخدم %s", message.from_user.id)

    # ================== الرسائل غير المعروفة ==================
    # يُسجَّل أخيراً ليلتقط فقط ما لم تلتقطه معالجات الأوامر الأخرى
    @bot.message_handler(
        content_types=["text"],
        func=lambda m: not (m.text or "").lstrip().startswith("/"),
    )
    @admin_only
    def handle_unknown(message):
        # الرسائل النصية العادية تُتجاهل (البوت أوامري فقط)
        logger.info("رسالة نصية عادية من %s تم تجاهلها", message.from_user.id)
