"""تنبيه عن بعد: نغمة (مع رفع الصوت) + فلاش + اهتزاز، كل واحد لحاله أو معاً.

الفكرة بالنسبة للكتم: وضع الصامت/الاهتزاز بأندرويد بيكتم الرنين والإشعارات بس، أما
مجرى الوسائط (music) فمستقل عنه. فنرفع صوت music لأقصى حد، نشغّل النغمة، وبالآخر
نرجّع الصوت لقيمته الأصلية. ملاحظة: وضع "عدم الإزعاج - صمت تام" (DND) بيكتم كل شي
ولا يقدر Termux:API يغيّره.
"""

import json
import math
import struct
import subprocess
import threading
import time
import wave
from pathlib import Path

from phone_status_bot.core import config
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.termux import resolve_termux_bin

DEFAULT_SECONDS = 20
MAX_SECONDS = 120
_WAV = Path(config.TERMUX_TMPDIR) / "mybot_alert.wav"

_lock = threading.Lock()
_stop = threading.Event()
_thread = None


def _run(cmd, timeout=10):
    try:
        return subprocess.run(
            [resolve_termux_bin(cmd[0])] + cmd[1:],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("فشل تنفيذ %s: %s", cmd[0], e)
        return None


def _ensure_wav():
    """توليد نغمة تنبيه قصيرة (ثانية) مرة واحدة بدون ملفات جاهزة."""
    if _WAV.exists() and _WAV.stat().st_size > 0:
        return _WAV
    rate = 22050
    frames = bytearray()
    for freq in (880, 1320, 880, 1320):
        for i in range(int(rate * 0.25)):
            frames += struct.pack("<h", int(30000 * math.sin(2 * math.pi * freq * i / rate)))
    _WAV.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(_WAV), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return _WAV


def _music_volume():
    """(الحالي، الأقصى) لمجرى music أو None."""
    r = _run(["termux-volume"])
    try:
        for s in json.loads(r.stdout):
            if s.get("stream") == "music":
                return int(s["volume"]), int(s["max_volume"])
    except Exception:
        pass
    return None


def is_active():
    return _thread is not None and _thread.is_alive()


def start(sound, flash, vibrate, seconds):
    """بدء تنبيه بخيط خلفي. ترجع False إذا في تنبيه شغّال أصلاً."""
    global _thread
    seconds = max(1, min(int(seconds), MAX_SECONDS))
    with _lock:
        if is_active():
            return False
        _stop.clear()
        _thread = threading.Thread(
            target=_worker, args=(sound, flash, vibrate, seconds), daemon=True)
        _thread.start()
        return True


def stop():
    """إيقاف التنبيه الحالي (إن وُجد) وانتظار تنظيفه."""
    _stop.set()
    t = _thread
    if t is not None and t.is_alive():
        t.join(timeout=15)


def _worker(sound, flash, vibrate, seconds):
    end = time.monotonic() + seconds
    prev_volume = None
    torch_on = False
    next_sound = next_vibe = next_flash = 0.0
    try:
        wav = None
        if sound:
            vol = _music_volume()
            if vol:
                prev_volume = vol[0]
                _run(["termux-volume", "music", str(vol[1])])
            wav = _ensure_wav()

        while not _stop.is_set() and time.monotonic() < end:
            now = time.monotonic()
            if sound and now >= next_sound:
                _run(["termux-media-player", "play", str(wav)])
                next_sound = time.monotonic() + 1.2
            if vibrate and now >= next_vibe:
                _run(["termux-vibrate", "-d", "800", "-f"])
                next_vibe = time.monotonic() + 1.2
            if flash and now >= next_flash:
                torch_on = not torch_on
                _run(["termux-torch", "on" if torch_on else "off"])
                next_flash = time.monotonic() + 0.5
            _stop.wait(0.2)
    except Exception as e:
        logger.exception("خطأ في التنبيه: %s", e)
    finally:
        if sound:
            _run(["termux-media-player", "stop"])
            if prev_volume is not None:
                _run(["termux-volume", "music", str(prev_volume)])
        if flash:
            _run(["termux-torch", "off"])
