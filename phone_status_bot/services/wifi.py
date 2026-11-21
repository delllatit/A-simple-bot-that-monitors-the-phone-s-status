"""تغيير شبكة Wi-Fi المتصل بها الجهاز.

Android لا يسمح للتطبيقات العادية (ومنها Termux بدون root) بالاتصال بشبكة
Wi-Fi جديدة برمجياً مباشرة، لكن Termux:API يوفر أمر `am` الذي يرسل
broadcast يستقبله MacroDroid وينفذ مهمة "Connect to WiFi network" — وهذا
يعمل مع الشبكات المحفوظة في الهاتف دون الحاجة لإدخال كلمة مرور.

التصميم الحالي (بدون root):
   البوت يرسل broadcast عبر Termux:API (`am broadcast`) يحمل اسم الشبكة،
   وماكرو MacroDroid ينفذ الاتصال بالشبكة المحفوظة.
   يجب إنشاء ماكرو في MacroDroid:
       Trigger : Receive Intent / Broadcast
                 Action : com.macrodroid.intent.action.CONNECT_WIFI
                 Extra  : ssid (نص)
       Action  : Connect to WiFi network → قيمة الـ Extra "ssid"
                 (اترك خانة كلمة المرور فارغة للشبكات المحفوظة)

طريقة متقدمة (اختيارية، تتطلب root):
   - قراءة الشبكات المحفوظة من WifiConfigStore.xml لأمر /wifi list.
   - إعادة تشغيل واجهة Wi-Fi (svc wifi disable ثم enable) للتبديل بين
     الشبكات المحفوظة حسب الأولوية.

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
    """إرسال broadcast عبر Termux:API (`am`) لـ MacroDroid للاتصال بالشبكة.

    password اختيارية: إذا كانت الشبكة محفوظة في الهاتف فلن يحتاج الماكرو
    كلمة مرور (اترك خانة كلمة المرور فارغة في إجراء MacroDroid).

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
