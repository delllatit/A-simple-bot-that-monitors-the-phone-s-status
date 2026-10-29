"""صلاحيات المسؤولين وزخرفة الحماية (admin_only) مع حد عدد الطلبات."""

import functools
import threading
import time

import telebot

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger

rate_limit_state = {}
rate_limit_lock = threading.Lock()


def is_admin(message):
    """هل مُرسل الرسالة من المسؤولين المعتمدين؟"""
    return bool(message.from_user) and message.from_user.id in config.ADMIN_IDS


def admin_only(func):
    """زخرفة للتحقق من صلاحيات المسؤول + حد عدد الطلبات، بدلاً من تكرار الفحص.

    - ترفض غير المسؤولين برسالة عامة وتسجّل المحاولة.
    - تفرض نافذة تبريد (RATE_LIMIT_WINDOW) لكل مستخدم لمنع الإغراق.
    - تلتقط أخطاء Telegram API والأخطاء غير المتوقعة: التفاصيل الكاملة في
      السجل فقط، ورسالة عامة للمستخدم دون كشف بيانات حساسة.
    """

    @functools.wraps(func)
    def wrapper(message, *args, **kwargs):
        if not is_admin(message):
            uid = getattr(message.from_user, "id", "unknown")
            logger.warning("محاولة وصول غير مصرح بها من المستخدم %s", uid)
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


def safe_send(chat_id, text, **kwargs):
    """إرسال رسالة إلى محادثة معينة مع تسجيل الفشل بدل رفعه."""
    try:
        return state.bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error("فشل إرسال تنبيه إلى %s: %s", chat_id, e)
        return None
