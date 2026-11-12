"""تغيير شبكة Wi-Fi المتصل بها الجهاز.

Android لا يسمح للتطبيقات العادية (ومنها Termux بدون root) بالاتصال بشبكة
Wi-Fi جديدة برمجياً مباشرة، لأن ذلك يتطلب صلاحيات نظام خاصة. لذلك يعتمد
هذا الملف طريقتين:

1) الطريقة الافتراضية (بدون root) — عبر MacroDroid مثل أمر /hotspot:
   يرسل البوت broadcast يحمل اسم الشبكة وكلمة المرور إلى MacroDroid،
   وقواعد MacroDroid تنفذ الاتصال (بعد منح MacroDroid صلاحية الموقع/Wi-Fi).
   يجب إنشاء ماكرو في MacroDroid:
       Trigger : Receive Intent / Broadcast بالـ Action التالي:
                 com.termux.WIFI_CONNECT  + Extra اسمه ssid (وpassword اختيارياً)
       Action  : Connect to WiFi network (بقيم الـ Extras)

2) طريقة متقدمة (جذور فقط):
   - قراءة الشبكات المحفوظة من WifiConfigStore.xml.
   - التبديل بين شبكتين محفوظتين بإعادة تشغيل واجهة Wi-Fi (svc wifi disable
     ثم enable)، أو تعديل <priority> / حذف الشبكة الأخرى من الملف للتحكم الدقيق.

مدخلات المستخدم تُتحقق منها بـ is_valid_ssid لمنع حقن الأوامر، وتُمرَّر
دائماً كقوائم مفصولة بدون shell=True.
"""

import re
import subprocess

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

# الـ Action المتفق عليه مع MacroDroid
MACROIDROID_WIFI_ACTION = "com.termux.WIFI_CONNECT"

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


def list_saved_networks():
    """قراءة أسماء الشبكات المحفوظة (يتطلب root).

    يرجع (قائمة_مراتب, None) عند النجاح، أو ([], رسالة_خطأ) عند التعذر.
    """
    for path in WIFI_CONFIG_CANDIDATES:
        try:
            result = subprocess.run(
                ["su", "-c", f"cat '{path}'"],
                capture_output=True, text=True, timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        if result.returncode != 0 or not result.stdout.strip():
            continue
        ssids = set(re.findall(r'SSID="([^"]+)"', result.stdout))
        ssids.discard("<unknown ssid>")
        return sorted(ssids), None
    return [], ("تعذر قراءة قائمة الشبكات المحفوظة — هذه الميزة تتطلب "
                "صلاحيات root لقراءة ملف إعدادات Wi-Fi.")


def connect_via_macrodroid(ssid, password=None):
    """إرسال broadcast لـ MacroDroid للاتصال بالشبكة المعطاة.

    True = أُرسل الأمر (وليس ضماناً لنجاح الاتصال؛ التحقق يتم عبر
    get_connected_ssid بعد ثوانٍ).
    """
    args = [
        resolve_termux_bin("am"), "broadcast",
        "-a", MACROIDROID_WIFI_ACTION,
        "--es", "ssid", ssid,
    ]
    if password:
        args += ["--es", "password", password]
    out = run_termux_command(args, timeout=10)
    logger.info("wifi.connect عبر MacroDroid: %r -> %r", ssid, out[:80])
    return not out.startswith("خطأ")


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
