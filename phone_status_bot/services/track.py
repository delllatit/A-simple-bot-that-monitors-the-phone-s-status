"""وضع التتبّع (Lost mode): إرسال موقع الهاتف للمسؤولين كل N دقيقة لحد الإيقاف.

الحالة (شغّال/متوقف + الفاصل) تنحفظ بملف، فلو انطفأ الهاتف أو البوت وقت الضياع
بيكمل التتبّع تلقائياً بعد الإقلاع. المواقع اللي ما انبعتت (انقطاع نت) بتنحفظ
بالطابور الدائم وبتوصل لاحقاً مع وقتها الأصلي.
"""

import json
import os
import subprocess
import threading

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import safe_send
from phone_status_bot.services import location

DEFAULT_MINUTES = 10
MIN_MINUTES = 1
MAX_MINUTES = 120
FAILURES_BEFORE_WARNING = 3
_SECONDS_PER_MINUTE = 60  # للاختبار فقط

_lock = threading.Lock()
_wake = threading.Event()
_started = False


def _path():
    return config.DATA_DIR / "track.json"


def get_state():
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        minutes = int(data.get("minutes", DEFAULT_MINUTES))
        return {"active": bool(data.get("active")),
                "minutes": max(MIN_MINUTES, min(minutes, MAX_MINUTES))}
    except (OSError, ValueError, TypeError):
        return {"active": False, "minutes": DEFAULT_MINUTES}


def set_state(active, minutes=None):
    with _lock:
        cur = get_state()
        if minutes is not None:
            cur["minutes"] = max(MIN_MINUTES, min(int(minutes), MAX_MINUTES))
        cur["active"] = bool(active)
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = str(_path()) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cur, f)
            os.replace(tmp, _path())
        except OSError as e:
            logger.error("تعذر حفظ حالة التتبّع: %s", e)
    _wake.set()  # نبّه الخيط ليتصرف فوراً
    return cur


def _network_location():
    """موقع تقريبي من الشبكة (بيشتغل داخل المباني لما GPS ما يلقط)."""
    try:
        r = subprocess.run(["termux-location", "-p", "network", "-r", "once"],
                           capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
        lat, lon, acc = data.get("latitude"), data.get("longitude"), data.get("accuracy")
        if lat is None or lon is None:
            return None
        return {"latitude": lat, "longitude": lon,
                "accuracy": float(acc) if acc is not None else 0.0}
    except Exception:
        return None


def _battery_line():
    try:
        from phone_status_bot.services import battery
        data = battery.read_battery_status()
        if data and data.get("percentage") is not None:
            plugged = data.get("plugged", "")
            charging = " ⚡" if plugged and plugged != "UNPLUGGED" else ""
            return f"\n🔋 البطارية: {data['percentage']}%{charging}"
    except Exception:
        pass
    return ""


def _send_all(text, queue=True):
    for admin_id in config.ADMIN_IDS:
        safe_send(admin_id, text, queue=queue)


def _tick(failures):
    """قراءة موقع وإرساله. ترجع عدد الفشل المتتالي المحدّث."""
    loc = location.fetch_gps_location()
    approx = False
    if loc is None:
        loc = _network_location()
        approx = loc is not None
    if loc is None:
        failures += 1
        logger.warning("التتبّع: تعذر الحصول على موقع (%s متتالية)", failures)
        if failures == FAILURES_BEFORE_WARNING:
            _send_all("⚠️ التتبّع: تعذر الحصول على موقع الهاتف عدة مرات متتالية "
                      "(الموقع مغلق أو الهاتف داخل مبنى مغلق). بحاول مجدداً.", queue=False)
        return failures
    text = "🛰️ تتبّع الهاتف\n" + location.format_location_report(loc)
    if approx:
        text += "\n⚠️ تقريبي (موقع شبكة، GPS ما لقط)"
    text += _battery_line()
    _send_all(text)
    return 0


def track_worker():
    """خيط خلفي: يرسل الموقع كل N دقيقة طالما التتبّع فعّال."""
    failures = 0
    while not state.SHUTDOWN.is_set():
        st = get_state()
        if not st["active"]:
            failures = 0
            _wake.wait(60)
            _wake.clear()
            continue
        try:
            failures = _tick(failures)
        except Exception as e:
            logger.error("خطأ بالتتبّع: %s", e)
        _wake.wait(st["minutes"] * _SECONDS_PER_MINUTE)
        _wake.clear()


def start_worker():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=track_worker, daemon=True).start()
