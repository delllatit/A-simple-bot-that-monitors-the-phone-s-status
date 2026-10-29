"""معالجات النظام المحلي: /storage /cpu /contacts."""

from phone_status_bot.core.html_utils import send_html_reply
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import admin_only
from phone_status_bot.core import state
from phone_status_bot.services import system_info


def register(bot):
    state.init_bot(bot)

    # ================== /storage ==================
    @bot.message_handler(commands=["storage"])
    @admin_only
    def get_storage_info(message):
        """عرض مساحة القرص باستخدام مكتبة بايثون المدمجة (لا تحتاج df)."""
        report = system_info.get_storage_report()
        if report is None:
            bot.reply_to(message, "❌ تعذر قراءة معلومات التخزين.")
            return
        send_html_reply(bot, message, report)
        logger.info("تم جلب مساحة القرص للمستخدم %s", message.from_user.id)

    # ================== /cpu ==================
    @bot.message_handler(commands=["cpu"])
    @admin_only
    def get_cpu_info(message):
        """عرض استخدام المعالج والذاكرة من /proc."""
        try:
            report = system_info.get_cpu_report()
        except Exception:
            logger.exception("خطأ في جلب معلومات المعالج")
            bot.reply_to(message, "❌ حدث خطأ أثناء جلب معلومات المعالج. راجع سجل البوت.")
            return
        send_html_reply(bot, message, report)
        logger.info("تم جلب معلومات المعالج للمستخدم %s", message.from_user.id)

    # ================== /contacts ==================
    @bot.message_handler(commands=["contacts"])
    @admin_only
    def get_contacts(message):
        """عرض جهات الاتصال (بحد أقصى 100 لتجنب الرسائل الضخمة)."""
        try:
            contacts = system_info.fetch_contacts()
        except FileNotFoundError:
            bot.reply_to(message, "❌ أمر termux-contact-list غير موجود. تأكد من تثبيت Termux:API.")
            logger.error("termux-contact-list غير موجود")
            return
        except RuntimeError as e:
            detail = str(e)
            if detail == "empty_output":
                bot.reply_to(message, "❌ الأمر نُفذ بنجاح لكن النتيجة فارغة! "
                                      "تأكد من منح تطبيق Termux:API إذن جهات الاتصال.")
            elif detail == "invalid_json":
                bot.reply_to(message, "❌ تعذر تحليل بيانات جهات الاتصال. راجع سجل البوت.")
            elif detail == "unexpected_format":
                bot.reply_to(message, "❌ صيغة غير متوقعة من termux-contact-list.")
            else:
                # التفاصيل الكاملة (مخرجات النظام) في اللوج فقط
                bot.reply_to(message, "❌ تعذر قراءة جهات الاتصال. تأكد من أذونات Termux:API.")
                logger.warning("فشل termux-contact-list: %s", detail)
            return

        report = system_info.format_contacts_report(contacts)
        send_html_reply(bot, message, report)
        logger.info("تم جلب جهات الاتصال (%d) للمستخدم %s", len(contacts), message.from_user.id)
