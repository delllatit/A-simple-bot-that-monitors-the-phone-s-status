"""صلاحيات المسؤولين وزخرفة الحماية (admin_only) مع حد عدد الطلبات."""

import functools
import html
import threading
import time

import telebot

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger

rate_limit_state = {}
rate_limit_lock = threading.Lock()

UNAUTH_COOLDOWN = 600        # تنبيه واحد لكل غريب كل 10 دقائق
UNAUTH_MAX_PER_HOUR = 20     # سقف عام لمنع الإغراق
_unauth_last = {}
_unauth_times = []


def is_admin(message):
    """هل مُرسل الرسالة من المسؤولين المعتمدين؟"""
    return bool(message.from_user) and message.from_user.id in config.ADMIN_IDS


def _alert_unauthorized(message):
    """إشعار المسؤولين بمحاولة وصول غير مصرح بها (مع تبريد وسقف لمنع الإغراق)."""
    try:
        user = message.from_user
        uid = getattr(user, "id", None)
        now = time.monotonic()
        with rate_limit_lock:
            if now - _unauth_last.get(uid, -1e9) < UNAUTH_COOLDOWN:
                return
            _unauth_times[:] = [t for t in _unauth_times if now - t < 3600]
            if len(_unauth_times) >= UNAUTH_MAX_PER_HOUR:
                return
            if len(_unauth_last) > 1000:
                _unauth_last.clear()
            _unauth_last[uid] = now
            _unauth_times.append(now)
        name = " ".join(filter(None, [getattr(user, "first_name", None),
                                      getattr(user, "last_name", None)])) or "—"
        username = f"@{user.username}" if getattr(user, "username", None) else "—"
        command = html.escape((message.text or "")[:100])
        text = (
            "🚨 <b>محاولة وصول غير مصرح بها</b>\n"
            f"👤 الاسم: {html.escape(name)}\n"
            f"🔗 المعرّف: {html.escape(username)}\n"
            f"🆔 ID: <code>{uid}</code>\n"
            f"💬 الأمر: <code>{command}</code>"
        )
        for admin_id in config.ADMIN_IDS:
            safe_send(admin_id, text, parse_mode="HTML", queue=True)
    except Exception as e:
        logger.error("فشل تنبيه المسؤول بمحاولة وصول غريبة: %s", e)


def admin_only(func):
    """زخرفة للتحقق من صلاحيات المسؤول + حد عدد الطلبات، بدلاً من تكرار الفحص.

    - ترفض غير المسؤولين برسالة عامة وتسجّل المحاولة وتنبّه المسؤول.
    - تفرض نافذة تبريد (RATE_LIMIT_WINDOW) لكل مستخدم لمنع الإغراق.
    - تلتقط أخطاء Telegram API والأخطاء غير المتوقعة: التفاصيل الكاملة في
      السجل فقط، ورسالة عامة للمستخدم دون كشف بيانات حساسة.
    """

    @functools.wraps(func)
    def wrapper(message, *args, **kwargs):
        if not is_admin(message):
            uid = getattr(message.from_user, "id", "unknown")
            logger.warning("محاولة وصول غير مصرح بها من المستخدم %s", uid)
            _alert_unauthorized(message)
            _safe_reply(message, "🚫 عذراً، هذا البوت خاص بالمسؤول فقط.")
            return

        now = time.monotonic()
        with rate_limit_lock:
            last = rate_limit_state.get(message.from_user.id, 0)
            if now - last < config.RATE_LIMIT_WINDOW:
                return
            rate_limit_state[message.from_user.id] = now

        try:
            return func(message, *args, **kwargs)
        except telebot.apihelper.ApiTelegramException as e:
            # التفاصيل الكاملة في اللوج فقط — رسالة عامة للمستخدم
            # (BOT_ERROR لا يُعاد إرساله عبر reply_to)
            logger.exception("خطأ في Telegram API أثناء معالجة الأمر: %s", e)
            if getattr(e, "error_code", None) != 429:
                _safe_reply(message, "❌ حدث خطأ أثناء الاتصال بـ Telegram. راجع سجل البوت.")
        except Exception as e:
            # لا نبتلع الأخطاء غير المتوقعة بصمت
            logger.exception("خطأ غير متوقع في %s: %s", func.__name__, e)
            # عدم كشف نص الاستثناء للمستخدم (قد يحوي مسارات/بيانات حساسة)
            _safe_reply(message, "❌ حدث خطأ غير متوقع. راجع سجل البوت.")

    return wrapper


def _safe_reply(message, text, **kwargs):
    """الرد على رسالة دون رفع استثناء حتى لو فشل الإرسال نفسه."""
    try:
        return state.bot.reply_to(message, text, **kwargs)
    except Exception:
        pass


def safe_send(chat_id, text, queue=False, **kwargs):
    """إرسال رسالة إلى محادثة معينة مع تسجيل الفشل بدل رفعه.

    queue=True: عند الفشل (مثلاً انقطاع إنترنت) تُحفظ بطابور دائم وتُعاد لاحقاً.
    """
    try:
        return state.bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error("فشل إرسال تنبيه إلى %s: %s", chat_id, e)
        if queue:
            from phone_status_bot.core import outbox
            outbox.enqueue(chat_id, text, kwargs.get("parse_mode"))
        return None
