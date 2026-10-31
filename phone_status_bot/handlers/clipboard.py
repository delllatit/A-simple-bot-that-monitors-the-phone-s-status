
import subprocess

from phone_status_bot.core import state
from phone_status_bot.core.permissions import admin_only
from phone_status_bot.core.termux import resolve_termux_bin
from phone_status_bot.core.logging_setup import logger


def register(bot):
    state.init_bot(bot)

    @bot.message_handler(commands=["clipboard"])
    @admin_only
    def copy_to_clipboard(message):
        # النص المكتوب بعد الأمر
        text = (message.text or "").partition(" ")[2].strip()

        # إذا لم يوجد نص، نأخذ النص من الرسالة المردود عليها
        if not text and message.reply_to_message:
            text = message.reply_to_message.text or ""

        if not text:
            bot.reply_to(
                message,
                "⚠️ أرسل النص بعد الأمر أو استخدم الرد على رسالة.\n"
                "مثال:\n/clipboard مرحباً"
            )
            return

        try:
            subprocess.run(
                [resolve_termux_bin("termux-clipboard-set")],
                input=text,
                text=True,
                capture_output=True,
                timeout=10,
                check=True
            )

            bot.reply_to(message, "✅ تم حفظ النص في حافظة الهاتف.")

            logger.info(
                "تم نسخ نص إلى الحافظة بواسطة المستخدم %s",
                message.from_user.id
            )

        except Exception:
            logger.exception("فشل النسخ إلى الحافظة")
            bot.reply_to(message, "❌ فشل حفظ النص في الحافظة.")
