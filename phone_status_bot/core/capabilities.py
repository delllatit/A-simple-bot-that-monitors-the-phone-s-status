"""اكتشاف قدرات الجهاز عند التشغيل، وتعطيل الأوامر غير المدعومة برسالة واضحة.

الفكرة: بدل ما نفترض إنو كل شي شغال، نفحص الجهاز مرة وحدة (بدون ما نلمس
الكاميرا أو الرسائل أو غيرها)، ونخزّن النتيجة. كل أمر يعلن شو بيحتاج عبر
FEATURES، والزخرفة @requires("اسم_الميزة") تمنع تنفيذه برسالة مفهومة لو ناقص شي.

القيم: True = متاح، False = غير متاح، None = ما منقدر نتحقق (مثل MacroDroid).
"""

import functools
import html
import shutil
import subprocess
import threading

from phone_status_bot.core import state
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.termux import resolve_termux_bin

# اسم القدرة -> أمر termux-api اللازم
TERMUX_TOOLS = {
    "battery": "termux-battery-status",
    "wifi": "termux-wifi-connectioninfo",
    "cellinfo": "termux-telephony-cellinfo",
    "location": "termux-location",
    "camera": "termux-camera-photo",
    "microphone": "termux-microphone-record",
    "sms_send": "termux-sms-send",
    "sms_list": "termux-sms-list",
    "call": "termux-telephony-call",
    "contacts": "termux-contact-list",
    "clipboard": "termux-clipboard-set",
    "screencap": "termux-screencap",
}

# الميزة -> الأوامر + المتطلبات ("a|b" تعني: يكفي واحد منهم) + تلميح عند النقص
FEATURES = {
    "battery": {"cmds": "/battery", "needs": ["battery"],
                "hint": "ثبّت تطبيق Termux:API من نفس مصدر Termux (F-Droid أو GitHub)."},
    "wifi": {"cmds": "/network", "needs": ["wifi"], "hint": "يحتاج Termux:API."},
    "cellular": {"cmds": "/cellular", "needs": ["cellinfo"],
                 "hint": "يحتاج Termux:API وصلاحية الهاتف (Phone) لتطبيق Termux:API."},
    "location": {"cmds": "/location", "needs": ["location"],
                 "hint": "يحتاج Termux:API وصلاحية الموقع."},
    "photo": {"cmds": "/selfie /photo", "needs": ["camera"],
              "hint": "يحتاج Termux:API وصلاحية الكاميرا."},
    "record": {"cmds": "/record /stop", "needs": ["microphone"],
               "hint": "يحتاج Termux:API وصلاحية المايكروفون."},
    "sms": {"cmds": "/sms", "needs": ["sms_send"],
            "hint": "يحتاج Termux:API وصلاحية SMS."},
    "call": {"cmds": "/call", "needs": ["call"],
             "hint": "يحتاج Termux:API وصلاحية الهاتف."},
    "contacts": {"cmds": "/contacts", "needs": ["contacts"],
                 "hint": "يحتاج Termux:API وصلاحية جهات الاتصال."},
    "clipboard": {"cmds": "/clipboard", "needs": ["clipboard"],
                  "hint": "يحتاج Termux:API."},
    "screenshot": {"cmds": "/screenshot", "needs": ["screencap|adb"],
                   "hint": "يحتاج Termux:API (termux-screencap) أو adb."},
    # ما في طريقة موثوقة لفحصها من داخل Termux، فتظهر ❔
    "hotspot": {"cmds": "/hotspot", "needs": ["macrodroid"],
                "hint": "يحتاج ماكرو MacroDroid يستقبل hotspot.on / hotspot.off."},
    "bluetooth": {"cmds": "/bluetooth", "needs": ["macrodroid"],
                  "hint": "يحتاج ماكرو MacroDroid يستقبل bluetooth.on / bluetooth.off."},
}

_lock = threading.Lock()
_caps = None


def _run(cmd, timeout=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _readable(path):
    try:
        with open(path) as f:
            return bool(f.read(1))
    except OSError:
        return False


def _sdk():
    r = _run(["getprop", "ro.build.version.sdk"])
    out = r.stdout.strip() if r and r.returncode == 0 else ""
    return int(out) if out.isdigit() else 0


def detect():
    """فحص الجهاز وتخزين النتيجة. آمن: لا يلمس الكاميرا/المايك/الرسائل."""
    global _caps
    caps = {"sdk": _sdk()}

    # هل تطبيق Termux:API نفسه مثبّت ويرد؟ (الحزمة وحدها ما تكفي)
    r = _run([resolve_termux_bin("termux-battery-status")], timeout=10)
    api_live = bool(r and r.returncode == 0 and r.stdout.strip().startswith("{"))
    caps["api_live"] = api_live

    for cap, binary in TERMUX_TOOLS.items():
        present = shutil.which(resolve_termux_bin(binary)) is not None
        caps[cap] = present and api_live

    caps["adb"] = shutil.which("adb") is not None

    # الروت: قد يظهر طلب تأكيد (Magisk/KernelSU) أول مرة
    r = _run(["su", "-c", "id"], timeout=8)
    caps["root"] = bool(r and r.returncode == 0 and "uid=0" in r.stdout)

    caps["proc_stat"] = _readable("/proc/stat")
    caps["macrodroid"] = None  # غير قابل للتحقق

    with _lock:
        _caps = caps
    logger.info("قدرات الجهاز: %s", caps)
    if caps["sdk"] >= 31:
        logger.warning(
            "أندرويد %s: قد يقتل النظام عمليات Termux الفرعية (Phantom Process Killer). "
            "راجع إعدادات البطارية وخيار تعطيل قيود العمليات الفرعية.", caps["sdk"])
    return caps


def get(refresh=False):
    if refresh or _caps is None:
        return detect()
    return _caps


def _token(caps, name):
    return caps.get(name)


def _need_state(caps, need):
    """True / False / None لمتطلب واحد (يدعم a|b)."""
    states = [_token(caps, n) for n in need.split("|")]
    if any(s is True for s in states):
        return True
    if any(s is None for s in states):
        return None
    return False


def feature_state(feature, caps=None):
    caps = caps or get()
    states = [_need_state(caps, n) for n in FEATURES[feature]["needs"]]
    if any(s is False for s in states):
        return False
    if any(s is None for s in states):
        return None
    return True


def requires(feature):
    """زخرفة لمعالجات telebot: ترفض التنفيذ برسالة واضحة لو الميزة غير مدعومة.

    ضعها تحت @admin_only مباشرة. الحالة None (غير قابلة للتحقق) تمرّ.
    """
    def deco(func):
        @functools.wraps(func)
        def wrapper(message, *args, **kwargs):
            if feature_state(feature) is False:
                info = FEATURES[feature]
                state.bot.reply_to(
                    message,
                    f"⚠️ <b>{html.escape(info['cmds'])}</b> غير متاح على هالجهاز حالياً.\n"
                    f"{html.escape(info['hint'])}\n"
                    "بعد ما تصلحه ابعت <code>/capabilities refresh</code>.",
                    parse_mode="HTML",
                )
                return
            return func(message, *args, **kwargs)
        return wrapper
    return deco


def describe(refresh=False):
    caps = get(refresh)
    icon = {True: "✅", False: "❌", None: "❔"}
    lines = [
        "🧩 <b>قدرات الجهاز</b>",
        f"أندرويد API: <code>{caps['sdk'] or 'غير معروف'}</code>",
        f"روت: {icon[caps['root']]}   Termux:API: {icon[caps['api_live']]}   adb: {icon[caps['adb']]}",
        "",
    ]
    for name, info in FEATURES.items():
        lines.append(f"{icon[feature_state(name, caps)]} <code>{html.escape(info['cmds'])}</code>")
    lines.append("")
    lines.append("❔ = ما منقدر نتحقق منها (تعتمد على إعداد خارجي).")
    if caps["sdk"] >= 31:
        lines.append("⚠️ أندرويد 12+: استثنِ Termux من توفير البطارية وعطّل قيود العمليات الفرعية.")
    return "\n".join(lines)
