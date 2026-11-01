"""مراقبة أحداث الشاحن والـ Wi-Fi وإرسال تنبيه عند أي تغيّر."""

import socket
import time

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import safe_send
from phone_status_bot.core.termux import parse_json_output, run_termux_command

BATTERY_COMMAND = ["termux-battery-status"]
WIFI_COMMAND = ["termux-wifi-connectioninfo"]

CONFIRM_READINGS = 2   # عدد القراءات المتطابقة المطلوبة قبل اعتماد التغيّر (يمنع الوميض)
MAX_PENDING = 20       # أقصى عدد تنبيهات محفوظة أثناء انقطاع الإنترنت


class _Debounced:
    """يعتمد القيمة الجديدة فقط بعد تكرارها CONFIRM_READINGS مرة متتالية."""

    def __init__(self):
        self.confirmed = None
        self._candidate = None
        self._count = 0

    def update(self, value):
        """يرجع True فقط عند تأكّد تغيّر حقيقي (القراءة الأولى تُعتمد كأساس بدون تنبيه)."""
        if value is None:
            return False
        if value == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = value, 1
        if self._count < CONFIRM_READINGS:
            return False
        if self.confirmed is None:
            self.confirmed = value
            return False
        if value != self.confirmed:
            self.confirmed = value
            return True
        return False


def read_charging():
    """يرجع (هل الشاحن موصول، النسبة) أو None عند تعذر القراءة."""
    data = parse_json_output(run_termux_command(BATTERY_COMMAND))
    if not isinstance(data, dict) or "plugged" not in data:
        return None
    return str(data["plugged"]).upper() != "UNPLUGGED", data.get("percentage")


def _outbound_ip():
    """IP الذي يخرج منه الجهاز فعلياً (لا يرسل أي حزمة)؛ None إن لم توجد شبكة."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(2)
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def read_wifi():
    """يرجع (هل Wi-Fi متصل فعلاً، اسم الشبكة) أو None عند تعذر القراءة.

    termux-wifi-connectioninfo قد يرجع معلومات قديمة (COMPLETED) بعد إغلاق
    الواي فاي، لذلك نقارن IP الواي فاي بالـ IP الذي يخرج منه الجهاز فعلاً.
    """
    data = parse_json_output(run_termux_command(WIFI_COMMAND))
    if not isinstance(data, dict):
        return None
    wifi_ip = str(data.get("ip", "")).strip()
    if data.get("supplicant_state") != "COMPLETED" or wifi_ip in ("", "0.0.0.0"):
        return False, None
    if _outbound_ip() != wifi_ip:
        return False, None
    return True, str(data.get("ssid", "")).strip('"')


def _notify(text, pending):
    """يرسل لكل المسؤولين؛ ما فشل إرساله (مثلاً بدون إنترنت) يُحفظ ويُعاد لاحقاً."""
    for admin_id in config.ADMIN_IDS:
        if safe_send(admin_id, text, parse_mode="HTML") is None:
            if len(pending) < MAX_PENDING:
                pending.append((admin_id, text))


def _flush(pending):
    remaining = []
    for admin_id, text in pending:
        if safe_send(admin_id, text, parse_mode="HTML") is None:
            remaining.append((admin_id, text))
    pending[:] = remaining


def events_monitor():
    """حلقة المراقبة — تعمل في خيط خلفي حتى حدث SHUTDOWN."""
    charging_tracker = _Debounced()
    wifi_tracker = _Debounced()
    pending = []
    last_ssid = None

    while not state.SHUTDOWN.is_set():
        try:
            if pending:
                _flush(pending)
            now = time.strftime("%H:%M:%S")

            battery = read_charging()
            if battery is not None:
                charging, percentage = battery
                if charging_tracker.update(charging):
                    if charging:
                        text = f"🔌 <b>تم توصيل الشاحن</b>\n🔋 النسبة: {percentage}%\n🕐 {now}"
                    else:
                        text = f"🔋 <b>انفصل الشاحن</b>\n🔋 النسبة: {percentage}%\n🕐 {now}"
                    _notify(text, pending)

            wifi = read_wifi()
            if wifi is not None:
                connected, ssid = wifi
                if connected:
                    last_ssid = ssid
                if wifi_tracker.update(connected):
                    if connected:
                        text = f"📶 <b>اتصل بالـ Wi-Fi</b>\nالشبكة: {ssid}\n🕐 {now}"
                    else:
                        text = f"❌ <b>انقطع الـ Wi-Fi</b>\nآخر شبكة: {last_ssid or 'غير معروفة'}\n🕐 {now}"
                    _notify(text, pending)
        except Exception as e:
            logger.error("خطأ في مراقبة الأحداث: %s", e)

        state.SHUTDOWN.wait(config.EVENT_CHECK_INTERVAL)
