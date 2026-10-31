"""معالجات الشبكة والحالة: /ip /whois /network /cellular /battery."""

import subprocess

import requests

from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import admin_only
from phone_status_bot.core.termux import fetch_public_ip
from phone_status_bot.core import state
from phone_status_bot.services import battery, cellular, whois


def register(bot):
    state.init_bot(bot)

    # ================== /battery ==================
    @bot.message_handler(commands=["battery"])
    @admin_only
    def get_battery_info(message):
        report = battery.get_battery_report()
        if report is None:
            bot.reply_to(message, "تعذر قراءة بيانات البطارية. تحقق من Termux:API.")
            return
        bot.reply_to(message, report, parse_mode="HTML")
        logger.info("تم جلب معلومات البطارية للمستخدم %s", message.from_user.id)

    # ================== /ip ==================
    @bot.message_handler(commands=["ip"])
    @admin_only
    def get_ip(message):
        try:
            local_ip = cellular.get_local_ip()
            public_ip = fetch_public_ip() or "تعذر تحديده"
            bot.reply_to(message, f"📱 IP المحلي: {local_ip}\n🌍 IP العام: {public_ip}")
            logger.info("تم جلب IP للمستخدم %s", message.from_user.id)
        except Exception:
            logger.exception("فشل في جلب IP")
            bot.reply_to(message, "❌ تعذر جلب عنوان IP. راجع سجل البوت.")

    # ================== /whois ==================
    @bot.message_handler(commands=["whois"])
    @admin_only
    def handle_whois(message):
        try:
            parts = (message.text or "").split()
            if len(parts) < 2:
                bot.reply_to(
                    message,
                    "الاستخدام: /whois <عنوان IP>\nمثال: /whois 8.8.8.8\n"
                    "إذا لم تُحدد عنواناً سيُستخدم IP العام الحالي للجهاز.",
                )
                return

            arg = parts[1].strip()
            # التحقق من صحة المعرّف المسموح تمريره للأمر — منع حقن الأوامر
            if not whois.is_valid_target(arg):
                bot.reply_to(message, "❌ صيغة العنوان غير صحيحة.")
                return

            target = arg
            is_public_ip = False
            if arg.lower() in ("me", "my", "self"):
                target = fetch_public_ip()
                is_public_ip = True
                # fetch_public_ip قد يُرجع None بدون رفع استثناء — نتحقق قبل الاستخدام
                if not target or not whois.is_valid_target(target):
                    bot.reply_to(
                        message,
                        "❌ تعذر تحديد IP العام الحالي. جرّب /whois <عنوان IP>.",
                    )
                    logger.warning("fetch_public_ip أعاد قيمة غير صالحة: %r", target)
                    return

            raw, fallback = whois.run_whois(target)
            messages = whois.format_report(target, raw, is_public_ip)
            if not messages:
                bot.reply_to(
                    message,
                    f"🔎 نتائج whois للعنوان {target}\n\n"
                    f"لم يتم العثور على سجلات مطابقة.\n{fallback}",
                )
                logger.info("لا نتائج whois للعنوان %s", target)
                return

            # format_report تُرجع قائمة رسائل مقسّمة حسب حد Telegram (4096 حرفاً)
            for chunk in messages:
                bot.reply_to(message, chunk, parse_mode="HTML")
            logger.info(
                "تم تنفيذ whois للعنوان %s (%d رسالة) للمستخدم %s",
                target, len(messages), message.from_user.id,
            )
        except FileNotFoundError:
            bot.reply_to(message, "❌ أمر whois غير مثبت. ثبّته عبر: pkg install whois")
            logger.warning("أمر whois غير متوفر على الجهاز")
        except subprocess.TimeoutExpired:
            logger.exception("انتهت مهلة أمر whois")
            bot.reply_to(message, "❌ انتهت مهلة استعلام whois (30 ثانية).")
        except requests.RequestException:
            logger.exception("تعذر جلب IP العام لاستعلام whois")
            bot.reply_to(message, "❌ تعذر تحديد IP العام الحالي. جرّب /whois <عنوان IP>.")
        except Exception:
            logger.exception("فشل في تنفيذ استعلام whois")
            bot.reply_to(message, "❌ تعذر تنفيذ استعلام whois. راجع سجل البوت.")

    # ================== /network ==================
    @bot.message_handler(commands=["network"])
    @admin_only
    def get_network_info(message):
        report = cellular.get_wifi_report()
        if report is None:
            bot.reply_to(message, "تعذر قراءة معلومات الشبكة. تحقق من Termux:API.")
            return
        if report == cellular.NO_ACTIVE_WIFI:
            bot.reply_to(message, "لا يوجد اتصال Wi-Fi نشط حالياً.")
            return
        bot.reply_to(message, report, parse_mode="HTML")
        logger.info("تم جلب معلومات الشبكة للمستخدم %s", message.from_user.id)

    # ================== /cellular ==================
    @bot.message_handler(commands=["cellular", "signal"])
    @admin_only
    def get_cellular_info(message):
        report = cellular.get_cellular_report()
        if report is None:
            bot.reply_to(
                message,
                "تعذر قراءة معلومات الشبكة الخلوية. تأكد من تثبيت Termux:API ومنح إذن الهاتف، "
                "وأن الجهاز يدعم الشريحة/الاتصال الخلوي."
            )
            return
        bot.reply_to(message, report, parse_mode="HTML")
        logger.info("تم جلب المعلومات الخلوية للمستخدم %s", message.from_user.id)
