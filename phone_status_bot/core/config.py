"""إعدادات البوت: تحميل .env والتحقق من القيم الحرجة.

جميع القيم قابلة للضبط عبر متغيرات البيئة أو ملف .env:

- TELEGRAM_BOT_TOKEN   : توكن البوت (إلزامي)
- ADMIN_ID             : معرف المسؤول أو قائمة معرفات مفصولة بفواصل (إلزامي)
- BOT_LOG_FILE         : مسار ملف السجل (افتراضي: ~/bot-logs/mybot.log)
- BATTERY_CHECK_INTERVAL: فترة مراقبة البطارية بالثواني (افتراضي: 1800)
- RECORD_MAX_SECONDS   : الحد الأقصى لمدة التسجيل الصوتي (افتراضي: 600)
- RATE_LIMIT_WINDOW    : النافذة الزمنية لحد الطلبات لكل مستخدم بالثواني (افتراضي: 3)
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ================== ثوابت المشروع ==================
APP_NAME = "Phone Status Monitor Bot"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_IDS = {
    int(x)
    for x in re.split(r"[,\s]+", ADMIN_IDS_RAW)
    if x.strip().lstrip("-").isdigit()
}

LOG_FILE = os.getenv("BOT_LOG_FILE", str(Path.home() / "bot-logs" / "mybot.log"))
BATTERY_CHECK_INTERVAL = int(os.getenv("BATTERY_CHECK_INTERVAL", "1800"))
RECORD_MAX_SECONDS = int(os.getenv("RECORD_MAX_SECONDS", "600"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "3"))

# عتبات تنبيه البطارية (من الأعلى إلى الأدنى)
BATTERY_THRESHOLDS = [60, 50, 40, 30]

# مجلد العمل المشترك (سجلات وملفات تسجيل صوتي)
DATA_DIR = Path(LOG_FILE).parent
RECORDING_DIR = DATA_DIR

# مسارات افتراضية خاصة ببيئة Termux
TERMUX_PREFIX = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
TERMUX_TMPDIR = os.environ.get("TMPDIR", f"{TERMUX_PREFIX}/tmp")


def validate_settings():
    """التحقق من الإعدادات الحرجة عند بدء التشغيل؛ يرفع SystemExit برسالة واضحة."""
    if not BOT_TOKEN:
        raise SystemExit("❌ لم يتم العثور على TELEGRAM_BOT_TOKEN داخل ملف .env أو البيئة.")
    if not ADMIN_IDS:
        raise SystemExit(
            "❌ قيمة ADMIN_ID غير صحيحة أو فارغة. يجب أن تكون رقمًا مثل: 6002823280 "
            "(أو قائمة مفصولة بفواصل)"
        )
