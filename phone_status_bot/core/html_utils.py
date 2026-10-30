"""أدوات تنسيق HTML الخاصة برسائل Telegram: اقتطاع آمن وتراجع عند فشل التحليل.

مشكلة تُرصد في السجلات:
    ApiTelegramException: Error code: 400.
    Description: Bad Request: can't parse entities: Can't find end tag
                 corresponding to start tag "code"

سببها أن الاقتطاع النصي الخام لنص HTML (مثل `report[:3900] + "..."`) قد يقصّ
الرسالة في منتصف وسم <code>...</code> أو <b>...</b> فيبقى الوسم مفتوحاً دون
وسم إغلاق، وترفض Telegram تحليل الكيانات (entities) وتتوقف الحلقة polling.

الحل هنا:
- truncate_html(): يقتطع عند حد الطول ثم **يسدّ الوسوم المفتوحة** بترتيب صحيح.
- send_html_reply()/send_html_message(): يرسل بصيغة HTML، وعند رفض Telegram
  تحليل الوسوم يعيد المحاولة تلقائياً بنص عادي بعد إزالة الوسوم (fallback)،
  فلا تتعطل المعالجة ولا يتوقف الاستطلاع.
"""

import html as _html
import re

from phone_status_bot.core.logging_setup import logger

# الحد الرسمي لطول نص رسالة Telegram
TELEGRAM_MESSAGE_LIMIT = 4096
# هامش أمان للرموز المتعددة البايت والزيادات الطفيفة في الترميز
SAFE_MESSAGE_LIMIT = 4000
TRUNCATION_SUFFIX = "\n… (تم الاقتطاع)"

# الوسوم التي يدعمها Telegram في صيغة HTML
_ALLOWED_TAGS = ("b", "i", "u", "s", "span", "tg-spoiler", "code", "pre", "a", "blockquote")

_OPEN_TAG_RE = re.compile(r"<(" + "|".join(_ALLOWED_TAGS) + r")(?:\s[^>]*?)?/?>", re.IGNORECASE)
_CLOSE_TAG_RE = re.compile(r"</(" + "|".join(_ALLOWED_TAGS) + r")\s*>", re.IGNORECASE)
_BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def _is_void_or_self_closing(match):
    """هل الوسم غير يحتاج إغلاق؟ (<br/> أو وسم مغلق ذاتياً مثل <b/>)."""
    raw = match.group(0)
    return raw.rstrip().endswith("/>") or match.group(1).lower() == "br"


def close_open_tags(text):
    """سدّ جميع الوسوم المفتوحة في `text` بترتيب صحيح (التكرار الأخير أولاً).

    يتجاهل الوسوم المغلقة ذاتياً ووسم <br>. لا يغيّر النص إذا كانت الوسوم متوازنة.
    """
    stack = []
    pos = 0
    while pos < len(text):
        open_match = _OPEN_TAG_RE.search(text, pos)
        close_match = _CLOSE_TAG_RE.search(text, pos)

        if close_match and (not open_match or close_match.start() < open_match.start()):
            # وسم إغلاق: يُخرج المطابق الأحدث من المكدس إن وُجد
            if stack and stack[-1].lower() == close_match.group(1).lower():
                stack.pop()
            elif stack:
                # إغلاق غير مطابق — نتجاهله ونستمر (تسامح مع مخرجات غريبة)
                pass
            pos = close_match.end()
            continue

        if open_match:
            if not _is_void_or_self_closing(open_match):
                stack.append(open_match.group(1).lower())
            pos = open_match.end()
            continue

        break

    if not stack:
        return text
    closers = "".join(f"</{tag}>" for tag in reversed(stack))
    return text + closers


def truncate_html(text, limit=SAFE_MESSAGE_LIMIT, suffix=TRUNCATION_SUFFIX):
    """اقتطاع نص HTML بأمان: لا يقصّ في منتصف وسم ويسدّ الوسوم المفتوحة.

    - إذا كان النص ضمن الحد يُرجع كما هو.
    - وإلا يبحث عن نقطة قص آمنة (خارج أي وسم) قرب الحد، يحذف بقية وسم غير
      مكتمل إن وجد، يضيف اللاحقة، ثم يسدّ الوسوم المفتوحة.
    """
    if text is None:
        return None
    if len(text) <= limit:
        return text

    budget = max(1, limit - len(suffix))
    cut = text[:budget]

    # 1) نقطة القص تقع داخل اسم/خصائص وسم؟ → نعود إلى ما قبل فتحته
    last_lt = cut.rfind("<")
    if last_lt != -1 and cut.find(">", last_lt) == -1:
        cut = cut[:last_lt]

    # 2) نقطة القص تقع داخل كيان HTML (&...;)؟ → نعود إلى قبل الرمز &
    last_amp = cut.rfind("&")
    if last_amp != -1 and cut.find(";", last_amp) == -1:
        cut = cut[:last_amp]

    return close_open_tags(cut.rstrip() + suffix)


def strip_html_tags(text):
    """إزالة كل الوسوم من النص وتحويل الكيانات إلى صورها النصية (للـ fallback)."""
    if not text:
        return ""
    without_br = _BR_TAG_RE.sub("\n", text)
    no_tags = _ANY_TAG_RE.sub("", without_br)
    return _html.unescape(no_tags)


def _is_entity_parse_error(exc):
    """هل الاستثناء خطأ 400 خاص بفشل تحليل الكيانات (parse entities)؟"""
    code = getattr(exc, "error_code", None)
    description = str(getattr(exc, "description", "") or exc)
    return code == 400 and "can't parse entities" in description.lower()


def _send_with_fallback(send_callable, text, parse_mode="HTML", **kwargs):
    """تنفيذ الإرسال مع محاولة أولى بصيغة محددة ومحاولة احتياطية كنص عادي.

    `send_callable(text, parse_mode=...)` هي قفل يغلف الاستدعاء الفعلي للبوت.
    - إذا رفضت Telegram تحليل الوسوم (خطأ 400: can't parse entities) تُعاد
      المحاولة فوراً بعد إزالة الوسوم، فلا يفشل الأمر ولا يتوقف الاستطلاع.
    - أخطاء API الأخرى تُرفع كما هي ليتعامل معها المستدعي (admin_only مثلاً).
    """
    try:
        return send_callable(text, parse_mode=parse_mode, **kwargs)
    except Exception as exc:
        if not _is_entity_parse_error(exc):
            raise
        logger.warning("تعذر تحليل وسوم HTML في الرسالة، إعادة الإرسال كنص عادي: %s", exc)
        plain = truncate_html(strip_html_tags(text))
        return send_callable(plain, parse_mode=None, **kwargs)


def send_html_reply(bot, message, text, **kwargs):
    """رد آمن بصيغة HTML على رسالة (اقتطاع سليم + تراجع تلقائي إلى نص عادي)."""
    return _send_with_fallback(
        lambda content, parse_mode, **kw: bot.reply_to(message, content, parse_mode=parse_mode, **kw),
        truncate_html(text),
        **kwargs,
    )


def send_html_message(bot, chat_id, text, **kwargs):
    """إرسال آمن بصيغة HTML إلى محادثة (اقتطاع سليم + تراجع تلقائي إلى نص عادي)."""
    return _send_with_fallback(
        lambda content, parse_mode, **kw: bot.send_message(chat_id, content, parse_mode=parse_mode, **kw),
        truncate_html(text),
        **kwargs,
    )
