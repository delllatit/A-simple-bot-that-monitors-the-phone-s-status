"""معالجات الوسائط: /selfie /photo (كاميرا) و /location (GPS)."""

import threading

from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import admin_only, safe_send
from phone_status_bot.core import state
from phone_status_bot.services import camera, location


def register(bot):
    state.init_bot(bot)

    # ================== /selfie و /photo ==================
    @bot.message_handler(commands=["selfie", "photo"])
    @admin_only
    def handle_photo_request(message):
        command = (message.text or "").split()[0].split("@")[0].lower()
        camera_id = "1" if command == "/selfie" else "0"

        bot.reply_to(
            message,
            f"جاري التقاط الصورة بالكاميرا {'الأمامية' if camera_id == '1' else 'الخلفية'}...",
        )

        photo_path, camera_name = camera.take_photo(camera_id)
        try:
            if photo_path is None:
                bot.reply_to(
                    message,
                    "فشل التقاط الصورة. تحقق من أذونات الكاميرا وتطبيق Termux:API.",
                )
                return

            with open(photo_path, "rb") as photo:
                bot.send_photo(
                    message.chat.id, photo,
                    caption=f"تم التقاط الصورة بالكاميرا {camera_name}.",
                )
            logger.info("تم التقاط صورة بالكاميرا %s للمستخدم %s", camera_name, message.from_user.id)
        except Exception:
            logger.exception("خطأ في إرسال الصورة")
            bot.reply_to(message, "تعذر التقاط الصورة أو إرسالها.")
        finally:
            camera.delete_photo(photo_path)

    # ================== /location ==================
    @bot.message_handler(commands=["location"])
    @admin_only
    def get_location(message):
        """الجلب في خيط منفصل لأن GPS قد يستغرق حتى ~60 ثانية."""
        threading.Thread(target=_fetch_and_send_location, args=(message,), daemon=True).start()


def _fetch_and_send_location(message):
    """تنفيذ جلب الموقع وإرسال النتيجة (يعمل داخل خيط خلفي)."""
    loc = location.fetch_gps_location()
    if loc is None:
        safe_send(
            message.chat.id,
            "❌ تعذر الحصول على موقع GPS صالح.\nتأكد من تفعيل الموقع وصلاحية Termux:API.",
        )
        logger.warning("لم يتم الحصول على موقع GPS للمستخدم %s",
                       message.from_user.id if message.from_user else "unknown")
        return

    safe_send(message.chat.id, location.format_location_report(loc))
    logger.info("تم جلب موقع GPS للمستخدم %s", message.from_user.id)
