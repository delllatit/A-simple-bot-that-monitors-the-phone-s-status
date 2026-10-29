"""خدمة الكاميرا: التقاط صورة وحفظها مؤقتاً ثم حذفها."""

from pathlib import Path

from phone_status_bot.core import config
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.termux import run_termux_command


def take_photo(camera_id):
    """التقاط صورة بالكاميرا المحددة (0 خلفية / 1 أمامية).

    يرجع (مسار_الملف، اسم_الكاميرا بالعربية) عند النجاح، أو (None، الاسم) عند الفشل.
    يتكفل المستدعي بحذف الملف بعد الإرسال.
    """
    camera_name = "الأمامية" if camera_id == "1" else "الخلفية"
    photo_path = Path(config.TERMUX_TMPDIR) / f"mybot_photo_{camera_id}.jpg"

    try:
        result = run_termux_command(["termux-camera-photo", "-c", camera_id, str(photo_path)])
        if result.startswith("خطأ:") or not photo_path.exists() or photo_path.stat().st_size == 0:
            logger.warning("فشل التقاط صورة من الكاميرا %s: %s", camera_name, result)
            return None, camera_name
        return photo_path, camera_name
    except Exception as e:
        logger.exception("خطأ في التقاط الصورة: %s", e)
        return None, camera_name


def delete_photo(photo_path):
    """حذف ملف الصورة المؤقت بأمان."""
    if photo_path is None:
        return
    try:
        if photo_path.exists():
            photo_path.unlink()
    except OSError as e:
        logger.warning("فشل حذف ملف الصورة: %s", e)
