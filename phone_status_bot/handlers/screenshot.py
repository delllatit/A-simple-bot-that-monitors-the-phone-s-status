"""معالجات الشاشة: /screenshot (ويمكن إضافة /screenrecord لاحقاً)."""

import os
import subprocess

from phone_status_bot.core import state
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import admin_only

# مسار مؤقت داخل Termux
SCREENSHOT_PATH = "/data/data/com.termux/files/home/screenshot_temp.png"

@admin_only
def take_screenshot(message):
    bot = state.bot
    chat_id = message.chat.id
    bot.reply_to(message, "📸 جاري التقاط الشاشة...")

    try:
        # 1. محاولة termux-screencap (الأسرع والأخف)
        result = subprocess.run(
            ["termux-screencap", "-p", SCREENSHOT_PATH],
            capture_output=True, text=True, timeout=15
        )

        # 2. التحقق من النجاح
        if result.returncode != 0 or not os.path.exists(SCREENSHOT_PATH):
            logger.warning("فشل termux-screencap: %s", result.stderr)
            # محاولة بديلة عبر ADB إن وُجد
            if not _try_adb_screenshot():
                raise RuntimeError("تعذر التقاط الشاشة. تأكد من تثبيت Termux:API.")

        # 3. إرسال الصورة
        with open(SCREENSHOT_PATH, "rb") as photo:
            bot.send_photo(chat_id, photo, caption="📱 لقطة الشاشة الحالية")
        logger.info("تم إرسال لقطة الشاشة للمستخدم %s", message.from_user.id)

    except Exception as e:
        logger.exception("خطأ في /screenshot: %s", e)
        bot.reply_to(message, f"⚠️ فشل التقاط الشاشة: {e}")

    finally:
        # 4. تنظيف الملف المؤقت دائماً
        if os.path.exists(SCREENSHOT_PATH):
            try:
                os.remove(SCREENSHOT_PATH)
            except Exception as e:
                logger.warning("تعذر حذف ملف اللقطة: %s", e)


def _try_adb_screenshot():
    """محاولة بديلة باستخدام ADB."""
    try:
        with open(SCREENSHOT_PATH, "wb") as f:
            subprocess.run(["adb", "exec-out", "screencap", "-p"], stdout=f, check=True, timeout=10)
        return os.path.exists(SCREENSHOT_PATH) and os.path.getsize(SCREENSHOT_PATH) > 0
    except Exception as e:
        logger.warning("فشل ADB screenshot: %s", e)
        return False


def register(bot):
    state.init_bot(bot)
    bot.message_handler(commands=["screenshot"])(take_screenshot)
