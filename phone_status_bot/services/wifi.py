"""تغيير شبكة Wi-Fi المتصل بها الجهاز.

الاتصال بالشبكات المحفوظة يتم عبر Intent Broadcast إلى MacroDroid.
يجب أن يستقبل الماكرو Extra نصياً باسم ssid ثم ينفذ Connect to WiFi network.
لا تتطلب هذه الطريقة صلاحيات root.
"""

import re

from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.termux import (
    parse_json_output,
    resolve_termux_bin,
    run_termux_command,
)
from phone_status_bot.services.cellular import WIFI_COMMAND

# مسار ملف إعدادات Wi-Fi في Android (يتطلب root لقراءته)
WIFI_CONFIG_CANDIDATES = (
    "/data/misc/apexdata/com.android.wifi/WifiConfigStore.xml",  # Android 10+
    "/data/misc/wifi/WifiConfigStore.xml",                        # Android أقدم
)

# الـ Action المتفق عليه مع MacroDroid (اسم الشبكة في Extra اسمه ssid)
MACROIDROID_WIFI_ACTION = "com.macrodroid.intent.action.CONNECT_WIFI"

# أحرف ممنوعة في SSID لأنها خطيرة في سياق الأوامر/الـ Intents
_SSID_ALLOWED = re.compile(r'^[^\'"`$\\<>|;&\n\r]+$')


def is_valid_ssid(ssid):
    """قبول أحرف عادية فقط في اسم الشبكة — منع حقن الأوامر."""
    return bool(ssid) and 1 <= len(ssid) <= 64 and bool(_SSID_ALLOWED.match(ssid))


def get_connected_ssid():
    """اسم الشبكة المتصل بها حالياً، أو None عند عدم وجود اتصال نشط."""
    data = parse_json_output(run_termux_command(WIFI_COMMAND, timeout=15))
    if not data:
        return None
    supplicant = str(data.get("supplicant_state", "")).upper()
    if supplicant not in ("COMPLETED", "GROUP_HANDSHAKE_DONE"):
        return None
    ssid = str(data.get("ssid", "")).strip().strip('"')
    return ssid or None


def connect_via_macrodroid(ssid, password=None):
    """إرسال broadcast عبر Termux:API (`am`) لـ MacroDroid للاتصال بالشبكة.

    password اختيارية: إذا كانت الشبكة محفوظة في الهاتف فلن يحتاج الماكرو
    كلمة مرور (اترك خانة كلمة المرور فارغة في إجراء MacroDroid).

    True = أُرسل الأمر (وليس ضماناً لنجاح الاتصال؛ التحقق يتم عبر
    get_connected_ssid بعد ثوانٍ).
    """
    args = [
        resolve_termux_bin("am"), "broadcast",
        "-a", MACROIDROID_WIFI_ACTION,
        "-p", "com.arlosoft.macrodroid",
        "--es", "ssid", ssid,
    ]
    if password:
        args += ["--es", "password", password]
    out = run_termux_command(args, timeout=10)
    logger.info("wifi.connect عبر MacroDroid: ssid=%r output=%r", ssid, out[:300])
    return not out.startswith("خطأ") and "Broadcast completed" in out


def toggle_wifi_interface(enable):
    """تشغيل/إيقاف واجهة Wi-Fi عبر أمر svc (فعّال غالباً مع root).

    إيقاف Wi-Fi ثم تشغيله يجبر Android على إعادة الاتصال بأعلى شبكة
    محفوظة أولوية — تُستخدم لتبديل الشبكة بين شبكتين محفوظتين.
    """
    out = run_termux_command(
        [resolve_termux_bin("svc"), "wifi", "enable" if enable else "disable"],
        timeout=15,
    )
    return not out.startswith("خطأ")
