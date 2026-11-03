"""معالج /capabilities: عرض ما يدعمه الجهاز من ميزات البوت."""

from phone_status_bot.core import capabilities, state
from phone_status_bot.core.permissions import admin_only


def register(bot):
    state.init_bot(bot)

    @bot.message_handler(commands=["capabilities", "caps"])
    @admin_only
    def handle_capabilities(message):
        args = (message.text or "").lower().split()[1:]
        bot.reply_to(
            message,
            capabilities.describe(refresh="refresh" in args),
            parse_mode="HTML",
        )
