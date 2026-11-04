"""أمر /track: تشغيل/إيقاف تتبّع موقع الهاتف الدوري (وضع الضياع)."""

from phone_status_bot.core import state
from phone_status_bot.core.capabilities import requires
from phone_status_bot.core.permissions import admin_only
from phone_status_bot.services import track as track_service

USAGE = (
    "الاستعمال:\n"
    "<code>/track on [دقائق]</code> — بدء التتبّع (الافتراضي {d}، من {lo} إلى {hi})\n"
    "<code>/track off</code> — إيقاف التتبّع\n"
    "<code>/track</code> — الحالة"
).format(d=track_service.DEFAULT_MINUTES, lo=track_service.MIN_MINUTES,
         hi=track_service.MAX_MINUTES)


def register(bot):
    state.init_bot(bot)
    track_service.start_worker()  # يكمل تلقائياً بعد إعادة التشغيل إذا كان فعّالاً

    @bot.message_handler(commands=["track"])
    @admin_only
    @requires("location")
    def handle_track(message):
        args = (message.text or "").split()[1:]
        st = track_service.get_state()

        if not args:
            if st["active"]:
                bot.reply_to(message, f"📡 التتبّع شغّال: كل {st['minutes']} دقيقة.\n"
                                      "للإيقاف: /track off")
            else:
                bot.reply_to(message, "التتبّع متوقف.\n" + USAGE, parse_mode="HTML")
            return

        action = args[0].lower()
        if action in ("off", "stop", "ايقاف", "إيقاف"):
            track_service.set_state(False)
            bot.reply_to(message, "⏹ تم إيقاف التتبّع.")
        elif action == "on":
            minutes = st["minutes"]
            if len(args) > 1:
                if not args[1].isdigit():
                    bot.reply_to(message, USAGE, parse_mode="HTML")
                    return
                minutes = int(args[1])
            new = track_service.set_state(True, minutes)
            bot.reply_to(message, f"📡 بدأ التتبّع: كل {new['minutes']} دقيقة. "
                                  "أول موقع بعد شوي (قد ياخد حتى دقيقة).\n"
                                  "للإيقاف: /track off")
        else:
            bot.reply_to(message, USAGE, parse_mode="HTML")
