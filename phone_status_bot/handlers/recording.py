"""معالجات التسجيل الصوتي: /record و /stop."""

import threading

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import admin_only
from phone_status_bot.services import recording


def register(bot):
    state.init_bot(bot)

    @bot.message_handler(commands=["record"])
    @admin_only
    def start_recording(message):
        ok, detail = recording.start_recording()
        if not ok:
            if detail == "already_active":
                bot.reply_to(message, "⚠️ التسجيل يعمل بالفعل. أرسل /stop لإنهائه.")
            else:
                # التفاصيل الكاملة تُسجَّل في اللوج فقط، ولا تُعرض للمستخدم
                bot.reply_to(message, "❌ تعذر بدء التسجيل. تحقق من أذونات الميكروفون وTermux:API.")
                logger.warning("فشل بدء التسجيل: %s", detail)
            return

        bot.reply_to(
            message,
            f"🎙️ بدأ التسجيل الصوتي.\nأرسل /stop لإيقافه وإرسال الملف.\n"
            f"(إيقاف تلقائي بعد {config.RECORD_MAX_SECONDS // 60} دقيقة كحد أقصى)",
        )
        logger.info("بدأ تسجيل صوتي للمستخدم %s", message.from_user.id)
        # مراقب للإيقاف التلقائي إذا لم يُرسَل /stop
        threading.Thread(target=recording.auto_stop_watcher, daemon=True).start()

    @bot.message_handler(commands=["stop"])
    @admin_only
    def stop_recording(message):
        status, path = recording.stop_recording()

        if status == "no_recording":
            bot.reply_to(message, "ℹ️ لا يوجد تسجيل نشط.")
            return
        if status == "stop_failed":
            # عدم كشف مخرجات النظام الخام للمستخدم
            bot.reply_to(message, "❌ تعذر إيقاف التسجيل بأمان. راجع سجل البوت.")
            logger.warning("فشل إيقاف المسجل للتسجيل: %s", path)
            return
        if status == "empty_file":
            bot.reply_to(message, "❌ ملف التسجيل فارغ أو غير موجود.")
            logger.warning("ملف التسجيل فارغ أو غير موجود: %s", path)
            return

        try:
            bot.reply_to(message, "📤 جارٍ إرسال التسجيل...")
            with open(path, "rb") as audio_file:
                bot.send_audio(message.chat.id, audio_file, title="تسجيل صوتي")
            logger.info("تم إرسال التسجيل الصوتي للمستخدم %s", message.from_user.id)
        except Exception:
            logger.exception("خطأ أثناء إرسال التسجيل")
            bot.reply_to(message, "❌ حدث خطأ أثناء إيقاف التسجيل. راجع سجل البوت.")
        finally:
            recording.finish_and_delete(path)
