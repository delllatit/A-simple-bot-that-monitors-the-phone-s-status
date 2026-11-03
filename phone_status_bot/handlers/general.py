import datetime
import time

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import admin_only

BOT_START_TIME = datetime.datetime.now()

# حد تيليجرام الأقصى لطول الرسالة الواحدة
TELEGRAM_MAX_LEN = 4096

HELP_TEXT = (
    "👋 <b>أهلاً بك في بوت حالة الهاتف</b>\n"
    "<i>البوت أوامري فقط — أرسل الأمر مباشرة.</i>\n"
    "\n"
    "📸 <b>الكاميرا والوسائط</b>\n"
    "  <code>/selfie</code> — تصوير بالكاميرا الأمامية\n"
    "  <code>/photo</code> — تصوير بالكاميرا الخلفية\n"
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
    "\n"
    "ℹ️ <b>معلومات البوت</b>\n"
    "  <code>/uptime</code> — مدة تشغيل البوت\n"
    "  <code>/status</code> — حالة البوت\n"
    "  <code>/admins</code> — قائمة المسؤولين\n"
    "  <code>/help</code> — إظهار هذه الرسالة\n"
)

# حماية من تكرار خطأ الفاصلة
assert isinstance(HELP_TEXT, str), "HELP_TEXT يجب أن يكون نصاً وليس tuple"


def _split_message(text, limit=TELEGRAM_MAX_LEN):
    """تقسيم النص الطويل على حدود الأسطر دون كسر وسوم HTML."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current += line
    if current:
        chunks.append(current)
    return chunks


def format_uptime(start_time, now=None):
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
        for chunk in _split_message(HELP_TEXT):
            bot.reply_to(message, chunk, parse_mode="HTML",
                         disable_web_page_preview=True)
        logger.info("تم عرض قائمة الأوامر للمستخدم %s", message.from_user.id)

    # ... بقية المعالجات كما هي ...
