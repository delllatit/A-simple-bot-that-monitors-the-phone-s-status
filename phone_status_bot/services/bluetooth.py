"""تشغيل/إيقاف البلوتوث عبر MacroDroid (Intent broadcast)."""

from phone_status_bot.core.termux import resolve_termux_bin, run_termux_command

ACTION_ON = "bluetooth.on"
ACTION_OFF = "bluetooth.off"


def set_bluetooth(enable: bool) -> bool:
    """True = انرسل الأمر (مو ضمان إنه اشتغل)."""
    action = ACTION_ON if enable else ACTION_OFF
    out = run_termux_command(
        [resolve_termux_bin("am"), "broadcast", "-a", action], timeout=10
    )
    return not out.startswith("خطأ")
