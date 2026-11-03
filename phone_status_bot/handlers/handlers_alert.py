"""أوامر التنبيه عن بعد: /ring (نغمة+فلاش+اهتزاز) و /tone و /flash و /vibrate."""

from phone_status_bot.core import state
from phone_status_bot.core.capabilities import requires
from phone_status_bot.core.permissions import admin_only
from phone_status_bot.services import alert as alert_service

# (الأمر، نغمة، فلاش، اهتزاز، اسم الميزة، الوصف)
ALERTS = (
    ("ring", True, True, True, "ring", "نغمة + فلاش + اهتزاز"),
    ("tone", True, False, False, "tone", "نغمة فقط"),
    ("flash", False, True, False, "flash", "فلاش فقط"),
    ("vibrate", False, False, True, "vibrate", "اهتزاز فقط"),
)
STOP_WORDS = {"stop", "off", "ايقاف", "إيقاف"}


def register(bot):
    state.init_bot(bot)

    def make(cmd, sound, flash, vibrate, feature, label):
        @bot.message_handler(commands=[cmd])
        @admin_only
        @requires(feature)
        def handler(message):
            args = (message.text or "").split()[1:]
            if args and args[0].lower() in STOP_WORDS:
                alert_service.stop()
                bot.reply_to(message, "⏹ تم إيقاف التنبيه.")
                return
            seconds = alert_service.DEFAULT_SECONDS
            if args:
                if not args[0].isdigit():
                    bot.reply_to(message, f"الصيغة: /{cmd} [عدد الثواني] أو /{cmd} stop")
                    return
                seconds = min(int(args[0]), alert_service.MAX_SECONDS)
            if not alert_service.start(sound, flash, vibrate, seconds):
                bot.reply_to(message, f"في تنبيه شغّال حالياً. أرسل /{cmd} stop لإيقافه.")
                return
            bot.reply_to(message, f"🔔 {label} لمدة {seconds} ثانية. للإيقاف: /{cmd} stop")
        return handler

    for spec in ALERTS:
        make(*spec)
