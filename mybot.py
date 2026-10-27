
import telebot
import subprocess
import json
import os
import time
import requests
import html

# ================== الإعدادات ==================
TOKEN = "8830804066:AAFbV3CM8j85Gfg1STLt8ezF3nqIFCZ0po4"
ADMIN_ID = 6002823280
# ===============================================

bot = telebot.TeleBot(TOKEN)


def run_termux_command(command):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        return "خطأ: انتهت مهلة تنفيذ الأمر بعد 30 ثانية."

    except subprocess.CalledProcessError as e:
        error = e.stderr.strip() if e.stderr else str(e)
        return f"خطأ في تنفيذ الأمر: {error}"

    except FileNotFoundError:
        return "خطأ: الأمر غير موجود. تأكد من تثبيت Termux:API."

    except OSError as e:
        return f"خطأ في النظام: {e}"


def is_admin(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "عذراً، هذا البوت خاص بك فقط.")
        return False
    return True


def parse_json_output(output):
    if output.startswith("خطأ:"):
        return None

    try:
        return json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None


# --- أمر البدء ---
@bot.message_handler(commands=["start"])
def send_welcome(message):
    if not is_admin(message):
        return

    text = (
        "أهلاً بك! الأوامر المتاحة:\n"
        "/selfie - التقاط صورة بالكاميرا الأمامية\n"
        "/photo - التقاط صورة بالكاميرا الخلفية\n"
        "/battery - معلومات البطارية\n"
        "/network - معلومات Wi-Fi\n"
        "/location - جلب الموقع الحالي عبر GPS"
        "/ip"
    )
    bot.reply_to(message, text)

import urllib.request
import json
import subprocess
import telebot

@bot.message_handler(commands=['ip'])
def get_ip(message):
    if not is_admin(message):
        return

    try:
        # عنوان IP المحلي من معلومات اتصال Wi-Fi
        result = subprocess.run(
            ['termux-wifi-connectioninfo'],
            capture_output=True,
            text=True,
            timeout=10
        )
        wifi = json.loads(result.stdout)
        local_ip = wifi.get('ip', 'غير متاح')

        # عنوان IP العام عبر الإنترنت
        result = subprocess.run(
            ['curl', '-4', '-sS', '--max-time', '10',
             'https://api.ipify.org'],
            capture_output=True,
            text=True,
            timeout=12,
            check=True
        )
        public_ip = result.stdout.strip()

        if not public_ip:
            public_ip = 'تعذر تحديده'

        bot.reply_to(
            message,
            f"📱 IP المحلي: {local_ip}\n"
            f"🌍 IP العام: {public_ip}"
        )

    except Exception as e:
        bot.reply_to(message, f"❌ تعذر جلب عنوان IP:\n{e}")


# --- التقاط صورة ---
@bot.message_handler(commands=["selfie", "photo"])
def handle_photo_request(message):
    if not is_admin(message):
        return

    command = message.text.split()[0].split("@")[0].lower()
    camera_id = "1" if command == "/selfie" else "0"
    camera_name = "الأمامية" if camera_id == "1" else "الخلفية"

    bot.reply_to(message, f"جاري التقاط الصورة بالكاميرا {camera_name}...")

    photo_path = os.path.join(
        os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp"),
        f"mybot_photo_{camera_id}.jpg"
    )

    try:
        result = run_termux_command([
            "termux-camera-photo",
            "-c", camera_id,
            photo_path
        ])

        if (
            result.startswith("خطأ:")
            or not os.path.isfile(photo_path)
            or os.path.getsize(photo_path) == 0
        ):
            bot.reply_to(
                message,
                "فشل التقاط الصورة. تحقق من أذونات الكاميرا وتطبيق Termux:API."
            )
            return

        with open(photo_path, "rb") as photo:
            bot.send_photo(
                message.chat.id,
                photo,
                caption=f"تم التقاط الصورة بالكاميرا {camera_name}."
            )

    except Exception as e:
        print(f"Camera error: {e}")
        bot.reply_to(message, "تعذر التقاط الصورة أو إرسالها.")

    finally:
        if os.path.isfile(photo_path):
            try:
                os.remove(photo_path)
            except OSError as e:
                print(f"Photo cleanup error: {e}")


# --- معلومات البطارية ---
@bot.message_handler(commands=["battery"])
def get_battery_info(message):
    if not is_admin(message):
        return

    output = run_termux_command(["termux-battery-status"])
    data = parse_json_output(output)

    if not isinstance(data, dict):
        bot.reply_to(message, "تعذر قراءة بيانات البطارية. تحقق من Termux:API.")
        print(f"Battery command output: {output}")
        return

    report = (
        "🔋 <b>معلومات البطارية:</b>\n"
        f"- <b>النسبة:</b> {html.escape(str(data.get('percentage', 'N/A')))}%\n"
        f"- <b>الحالة:</b> {html.escape(str(data.get('status', 'N/A')))}\n"
        f"- <b>الشحن:</b> {html.escape(str(data.get('plugged', 'N/A')))}\n"
        f"- <b>الصحة:</b> {html.escape(str(data.get('health', 'N/A')))}\n"
        f"- <b>الحرارة:</b> {html.escape(str(data.get('temperature', 'N/A')))} °C\n"
        f"- <b>التيار:</b> {html.escape(str(data.get('current', 'N/A')))} mA"
    )

    bot.reply_to(message, report, parse_mode="HTML")


# --- معلومات Wi-Fi ---
@bot.message_handler(commands=["network"])
def get_network_info(message):
    if not is_admin(message):
        return

    output = run_termux_command(["termux-wifi-connectioninfo"])
    data = parse_json_output(output)

    if not isinstance(data, dict):
        bot.reply_to(message, "تعذر قراءة معلومات الشبكة. تحقق من Termux:API.")
        print(f"Network command output: {output}")
        return

    if data.get("supplicant_state") != "COMPLETED":
        bot.reply_to(message, "لا يوجد اتصال Wi-Fi نشط حالياً.")
        return

    report = (
        "📶 <b>معلومات شبكة Wi-Fi:</b>\n"
        f"- <b>اسم الشبكة:</b> {html.escape(str(data.get('ssid', 'N/A')))}\n"
        f"- <b>عنوان IP:</b> {html.escape(str(data.get('ip', 'N/A')))}\n"
        f"- <b>BSSID:</b> {html.escape(str(data.get('bssid', 'N/A')))}\n"
        f"- <b>سرعة الاتصال:</b> {html.escape(str(data.get('link_speed_mbps', 'N/A')))} Mbps\n"
        f"- <b>قوة الإشارة:</b> {html.escape(str(data.get('rssi', 'N/A')))} dBm"
    )

    bot.reply_to(message, report, parse_mode="HTML")


# --- الموقع عبر GPS ---
@bot.message_handler(commands=["location"])
def get_location(message):
    if not is_admin(message):
        return

    msg = bot.reply_to(message, "جاري تحديد الموقع عبر GPS...")

    output = run_termux_command(["termux-location", "-p", "gps"])
    data = parse_json_output(output)

    if not isinstance(data, dict):
        bot.edit_message_text(
            "تعذر قراءة بيانات الموقع. تحقق من أذونات الموقع.",
            message.chat.id,
            msg.message_id
        )
        print(f"Location command output: {output}")
        return

    lat = data.get("latitude")
    lon = data.get("longitude")

    if lat is None or lon is None or lat == "" or lon == "":
        bot.edit_message_text(
            "لم يتم تحديد الإحداثيات. شغّل GPS وجرّب في مكان مفتوح.",
            message.chat.id,
            msg.message_id
        )
        return

    accuracy = data.get("accuracy", "N/A")
    gmaps_link = f"https://www.google.com/maps?q={lat},{lon}"

    report = (
        "📍 <b>الموقع الحالي:</b>\n"
        f"- <b>خط العرض:</b> {html.escape(str(lat))}\n"
        f"- <b>خط الطول:</b> {html.escape(str(lon))}\n"
        f"- <b>الدقة:</b> {html.escape(str(accuracy))} متر\n\n"
        f'<a href="{gmaps_link}">فتح الموقع على خرائط Google</a>'
    )

    bot.edit_message_text(
        report,
        message.chat.id,
        msg.message_id,
        parse_mode="HTML",
        disable_web_page_preview=True
    )


# --- تشغيل البوت وإعادة الاتصال ---
if not TOKEN or TOKEN == "ضع_التوكن_الجديد_هنا":
    raise SystemExit("ضع توكن البوت الجديد داخل TOKEN أولاً.")

print("البوت يعمل الآن...")

while True:
    try:
        bot.infinity_polling(
            timeout=30,
            long_polling_timeout=20,
            skip_pending=False
        )

    except requests.exceptions.ReadTimeout:
        print("انتهت مهلة الاتصال، ستتم إعادة المحاولة.")
        time.sleep(5)

    except requests.exceptions.RequestException as e:
        print(f"خطأ اتصال: {e}")
        time.sleep(10)

    except Exception as e:
        print(f"خطأ غير متوقع: {e}")
        time.sleep(5)

