"""مشاركة الحالة العامة بين الخيوط: نسخة البوت، حدث الإيقاف، وقفل التسجيل."""

import threading

# نسخة واحدة من البوت تُنشأ في main وتُحقن هنا لتفادي الاستيراد الدائري
# بين الوحدة الرئيسية والوحدات الفرعية.
bot = None

# حدث الإيقاف النظيف (يُشارَك بين الخيوط)
SHUTDOWN = threading.Event()

# حالة التسجيل الصوتي النشط
RECORDING_FILE = None
RECORDING_LOCK = threading.Lock()


def init_bot(telebot_instance):
    """حقن نسخة البوت بعد إنشائها في نقطة الدخول."""
    global bot
    bot = telebot_instance


def get_recording_file():
    """قراءة آمن لمسار التسجيل النشط."""
    with RECORDING_LOCK:
        return RECORDING_FILE


def take_recording_file():
    """استلام مسار التسجيل النشط وتفريغه ذرياً (يرجع None إن لم يوجد تسجيل)."""
    global RECORDING_FILE
    with RECORDING_LOCK:
        path = RECORDING_FILE
        RECORDING_FILE = None
    return path


def set_recording_file(path):
    """تعيين مسار التسجيل النشط."""
    global RECORDING_FILE
    with RECORDING_LOCK:
        RECORDING_FILE = path
