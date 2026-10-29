"""معالجات الهاتف والرسائل: /sms و /call."""

from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import admin_only
from phone_status_bot.core import state
from phone_status_bot.services import messaging


def register(bot):
    state.init_bot(bot)

    # ================== /sms ==================
    @bot.message_handler(commands=["sms"])
    @admin_only
    def send_sms(message):
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(message, "❌ استخدم الأمر بالشكل التالي:\n/sms 966500000000 مرحبا")
            return

        phone_number = messaging.normalize_phone(parts[1])
        sms_text = parts[2].strip()

        success, detail = messaging.send_sms(phone_number, sms_text)
        if detail == "invalid_input":
            bot.reply_to(message, "❌ رقم هاتف غير صالح. استخدم الصيغة الدولية مثل: 9665XXXXXXXX")
            return
        if not success:
            if "غير موجود" in (detail or ""):
                bot.reply_to(message, "❌ أمر termux-sms-send غير موجود. تأكد من تثبيت Termux:API ودعم SMS.")
                logger.error("termux-sms-send غير موجود")
            else:
                # التفاصيل في اللوج فقط، رسالة عامة للمستخدم
                bot.reply_to(message, "❌ تعذر إرسال رسالة SMS. تحقق من أذونات Termux:API.")
                logger.warning("فشل إرسال SMS إلى %s: %s", phone_number, detail)
            return

        bot.reply_to(message, f"✅ تم إرسال رسالة SMS إلى {phone_number}")
        logger.info("تم إرسال SMS إلى %s من المستخدم %s", phone_number, message.from_user.id)

    # ================== /call ==================
    @bot.message_handler(commands=["call"])
    @admin_only
    def make_call(message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "❌ استخدم الأمر بالشكل التالي:\n/call 966500000000")
            return

        phone_number = messaging.normalize_phone(parts[1])
        success, detail = messaging.make_call(phone_number)
        if detail == "invalid_input":
            bot.reply_to(message, "❌ رقم هاتف غير صالح. استخدم الصيغة الدولية مثل: 9665XXXXXXXX")
            return
        if not success:
            if "غير موجود" in (detail or ""):
                bot.reply_to(message, "❌ أمر termux-telephony-call غير موجود. تأكد من تثبيت Termux:API.")
                logger.error("termux-telephony-call غير موجود")
            else:
                # التفاصيل في اللوج فقط، رسالة عامة للمستخدم
                bot.reply_to(message, "❌ تعذر إجراء المكالمة. تحقق من أذونات Termux:API.")
                logger.warning("فشل termux-telephony-call إلى %s: %s", phone_number, detail)
            return

        bot.reply_to(message, f"📞 تم بدء المكالمة إلى {phone_number}")
        logger.info("تم بدء مكالمة إلى %s من المستخدم %s", phone_number, message.from_user.id)
