"""معالجات الشبكة والحالة: /ip /whois /network /cellular /battery /wifi."""

import time
import subprocess

import requests

from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import admin_only
from phone_status_bot.core.termux import fetch_public_ip
from phone_status_bot.core import state
import time

from phone_status_bot.services import battery, cellular, hotspot, whois, wifi

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

            # ================== /hotspot ==================
    @bot.message_handler(commands=["hotspot"])
    @admin_only
    def handle_hotspot(message):
        parts = (message.text or "").split()
        arg = parts[1].lower() if len(parts) > 1 else ""
        if arg not in ("on", "off"):
            bot.reply_to(message, "الاستخدام: /hotspot on أو /hotspot off")
            return

        ok = hotspot.set_hotspot(arg == "on")
        if ok:
            bot.reply_to(message, "📶 انرسل أمر " + ("التشغيل" if arg == "on" else "الإيقاف") + " لـ MacroDroid.")
        else:
            bot.reply_to(message, "❌ فشل إرسال الأمر. راجع سجل البوت.")
        logger.info("hotspot %s من المستخدم %s", arg, message.from_user.id)

    # ================== /wifi ==================
    @bot.message_handler(commands=["wifi"])
    @admin_only
    def handle_wifi(message):
        """تغيير شبكة Wi-Fi المتصل بها الجهاز.

        تعتمد الطريقة على Termux:API + MacroDroid (مثل /hotspot)، والاتصال
        يتم مع الشبكات المحفوظة في الهاتف دون الحاجة لكلمة مرور.

        الاستخدام:
            /wifi                     → عرض الشبكة الحالية والمساعدة
            /wifi list                → قائمة الشبكات المحفوظة (يتطلب root)
            /wifi <SSID>              → الاتصال بشبكة محفوظة عبر MacroDroid
            /wifi reconnect           → إعادة تشغيل واجهة Wi-Fi للتبديل بين
                                         الشبكات المحفوظة (الأعلى أولوية)
        """
        parts = (message.text or "").split(maxsplit=2)
        arg = parts[1].strip() if len(parts) > 1 else ""

        # --- بدون وسائط: عرض الشبكة الحالية + المساعدة ---
        if not arg:
            current = wifi.get_connected_ssid()
            if current:
                bot.reply_to(message, f"📡 الشبكة المتصل بها حالياً: <b>{current}</b>\n\n"
                                      "<code>/wifi &lt;SSID&gt;</code> — الاتصال بشبكة محفوظة (بدون كلمة مرور)\n"
                                      "<code>/wifi list</code> — الشبكات المحفوظة\n"
                                      "<code>/wifi reconnect</code> — إعادة الاتصال/التبديل",
                            parse_mode="HTML")
            else:
                bot.reply_to(message, "📡 لا يوجد اتصال Wi-Fi نشط حالياً.\n"
                                      "جرّب /wifi &lt;SSID&gt; للاتصال بشبكة محفوظة.",
                            parse_mode="HTML")
            return

        # --- /wifi list ---
        if arg.lower() == "list":
            networks, error = wifi.list_saved_networks()
            if error:
                bot.reply_to(message, f"❌ {error}")
                return
            if not networks:
                bot.reply_to(message, "لا توجد شبكات محفوظة قابلة للقراءة.")
                return
            current = wifi.get_connected_ssid()
            lines = [f"• <code>{n}</code>" + (" ⬅️ الحالية" if n == current else "") for n in networks]
            bot.reply_to(message,
                         "📋 الشبكات المحفوظة:\n" + "\n".join(lines),
                         parse_mode="HTML")
            logger.info("قائمة شبكات wi-Fi (%d) للمستخدم %s", len(networks), message.from_user.id)
            return

        # --- /wifi reconnect ---
        if arg.lower() == "reconnect":
            ok = wifi.toggle_wifi_interface(False) and wifi.toggle_wifi_interface(True)
            if not ok:
                bot.reply_to(message,
                             "❌ تعذر إعادة تشغيل واجهة Wi-Fi. غالباً تتطلب هذه الطريقة صلاحيات root.")
                return
            status = bot.reply_to(message, "🔄 أُعيد تشغيل Wi-Fi، جارٍ التحقق من الاتصال...")
            new_ssid = None
            for _ in range(10):
                time.sleep(3)
                new_ssid = wifi.get_connected_ssid()
                if new_ssid:
                    break
            if new_ssid:
                bot.edit_message_text(
                    status.chat.id, status.message_id,
                    f"✅ تم الاتصال بالشبكة: {new_ssid}",
                )
            else:
                bot.edit_message_text(
                    status.chat.id, status.message_id,
                    "⏳ لم يكتمل الاتصال بعد. تحقق لاحقاً عبر /network أو /wifi.",
                )
            logger.info("wifi reconnect من المستخدم %s -> %s", message.from_user.id, new_ssid)
            return

        # --- /wifi <SSID> : الاتصال بشبكة محفوظة (كلمة المرور اختيارية) ---
        ssid = arg
        password = parts[2].strip() if len(parts) > 2 else None
        if not wifi.is_valid_ssid(ssid):
            bot.reply_to(message, "❌ اسم الشبكة غير صالح (أحرف عادية فقط، حتى 64 حرفاً).")
            return

        current = wifi.get_connected_ssid()
        if current == ssid:
            bot.reply_to(message, f"✅ أنت متصل بالفعل بالشبكة: {ssid}")
            return

        if not wifi.connect_via_macrodroid(ssid, password):
            bot.reply_to(message, "❌ فشل إرسال الأمر إلى MacroDroid. راجع سجل البوت.")
            return

        status = bot.reply_to(
            message,
            f"📶 أُرسل أمر الاتصال بشبكة «{ssid}» إلى MacroDroid، جارٍ التحقق...",
        )
        # انتظار نجاح الاتصال مع فحص دوري (حتى ~30 ثانية)
        new_ssid = None
        for _ in range(10):
            time.sleep(3)
            new_ssid = wifi.get_connected_ssid()
            if new_ssid == ssid:
                break
        if new_ssid == ssid:
            bot.edit_message_text(status.chat.id, status.message_id,
                                  f"✅ تم الاتصال بنجاح بالشبكة: {ssid}")
        else:
            hint = ""
            if new_ssid:
                hint = f"\nالشبكة الحالية الآن: {new_ssid}"
            bot.edit_message_text(
                status.chat.id, status.message_id,
                "⚠️ أُرسل أمر الاتصال لكن لم يتم التأكد من نجاحه خلال 30 ثانية."
                f"{hint}\n"
                "تأكد من إعداد ماكرو في MacroDroid:\n"
                "• Trigger: Receive Intent بالـ Action "
                "`com.macrodroid.intent.action.CONNECT_WIFI` مع Extra اسمه `ssid`\n"
                "• Action: Connect to WiFi network بقيمة الـ Extra (اترك كلمة المرور فارغة للشبكات المحفوظة).",
            )
        logger.info("wifi connect '%s' من المستخدم %s -> connected='%s'",
                    ssid, message.from_user.id, new_ssid)
