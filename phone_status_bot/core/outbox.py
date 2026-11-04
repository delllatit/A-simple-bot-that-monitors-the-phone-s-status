"""طابور إرسال دائم: التنبيهات المهمة اللي فشل إرسالها (انقطاع إنترنت) تنحفظ بملف
وتُعاد لاحقاً، حتى لو البوت أو الهاتف انطفأ بالمنتصف (انقطاع الكهرباء).

الاستعمال: safe_send(chat_id, text, queue=True) أو outbox.enqueue(...) مباشرة.
"""

import json
import os
import threading
import time

import telebot

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger

MAX_ITEMS = 50                 # أقصى عدد رسائل محفوظة
MAX_AGE_SECONDS = 24 * 3600    # الرسالة الأقدم من يوم تُحذف (ما بتفيد متأخرة كتير)
RETRY_INTERVAL = 30            # ثانية بين محاولات الإرسال
_PERMANENT_CODES = {400, 403}  # أخطاء دائمة: ما بيفيد نعيد المحاولة

_lock = threading.Lock()
_items = None  # تُحمَّل عند أول استعمال


def _path():
    return config.DATA_DIR / "outbox.json"


def _load():
    global _items
    if _items is not None:
        return
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        _items = data if isinstance(data, list) else []
    except (OSError, ValueError):
        _items = []


def _save():
    """كتابة ذرّية: ملف مؤقت ثم استبدال (ما بيتخرب لو انقطعت الكهرباء بالنص)."""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = str(_path()) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_items, f, ensure_ascii=False)
        os.replace(tmp, _path())
    except OSError as e:
        logger.error("تعذر حفظ طابور الإرسال: %s", e)


def enqueue(chat_id, text, parse_mode=None):
    with _lock:
        _load()
        _items.append({"chat_id": chat_id, "text": text,
                       "parse_mode": parse_mode, "ts": time.time()})
        del _items[:-MAX_ITEMS]  # أبقِ الأحدث فقط
        _save()
    logger.info("تنبيه محفوظ بالطابور لحين رجوع الإنترنت (%s بالانتظار)", len(_items))


def pending_count():
    with _lock:
        _load()
        return len(_items)


def flush():
    """محاولة إرسال المحفوظ. بتتوقف عند أول فشل شبكة (ما منضرب الشبكة الميتة)."""
    with _lock:
        _load()
        now = time.time()
        _items[:] = [i for i in _items if now - i["ts"] < MAX_AGE_SECONDS]
        queue = list(_items)
    if not queue or state.bot is None:
        return 0
    sent = 0
    for item in queue:
        stamp = time.strftime("%H:%M", time.localtime(item["ts"]))
        text = f"🕓 (تأخر الإرسال، حدث الساعة {stamp})\n{item['text']}"
        done = False
        try:
            state.bot.send_message(item["chat_id"], text, parse_mode=item["parse_mode"])
            done = True
            sent += 1
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code in _PERMANENT_CODES:
                logger.error("حذف رسالة من الطابور (خطأ دائم %s)", e.error_code)
                done = True
            else:
                break
        except Exception:
            break  # غالباً ما في إنترنت
        finally:
            if done:
                with _lock:
                    if item in _items:
                        _items.remove(item)
                        _save()
    return sent


def outbox_worker():
    """خيط خلفي: يحاول تفريغ الطابور كل RETRY_INTERVAL ثانية حتى الإيقاف."""
    while not state.SHUTDOWN.is_set():
        try:
            if pending_count():
                flush()
        except Exception as e:
            logger.error("خطأ بخيط الطابور: %s", e)
        state.SHUTDOWN.wait(RETRY_INTERVAL)
