import os
import re
import json
import time
import html
import logging
import requests
import subprocess
from pathlib import Path

import telebot
from dotenv import load_dotenv


# ================== تحميل .env ==================
# هذا يقرأ الملف .env الموجود في نفس المجلد
load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "0").strip()
LOG_FILE = os.getenv("BOT_LOG_FILE", str(Path.home() / "bot-logs" / "mybot.log"))

# ================== إعدادات السجل ==================
LOG_DIR = Path(LOG_FILE).parent
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("telegram_bot")

if not BOT_TOKEN:
    raise SystemExit("❌ لم يتم العثور على TELEGRAM_BOT_TOKEN داخل ملف .env أو البيئة.")

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    raise SystemExit("❌ قيمة ADMIN_ID غير صحيحة. يجب أن تكون رقمًا مثل: 6002823280")

bot = telebot.TeleBot(BOT_TOKEN)


# ================== الإعدادات العامة ==================
RECORDING_FILE = None
RECORDING_DIR = Path.home() / "bot-logs"
RECORDING_DIR.mkdir(parents=True, exist_ok=True)


# ================== الوظائف المساعدة ==================
def is_admin(message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        try:
            bot.reply_to(message, "🚫 عذراً، هذا البوت خاص بالمسؤول فقط.")
        except Exception:
            pass
        logger.warning("محاولة وصول غير مصرح بها من المستخدم %s", getattr(message.from_user, "id", "unknown"))
        return False
    return True


def run_termux_command(command, timeout=30):
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout
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


def parse_json_output(output):
    if not output or output.startswith("خطأ:"):
        return None
    try:
        return json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None


# ================== /start و /help ==================
@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    if not is_admin(message):
        return

    text = (
        "أهلاً بك! الأوامر المتاحة:\n\n"
        "/selfie - تصوير بالكاميرا الأمامية\n"
        "/photo - تصوير بالكاميرا الخلفية\n"
        "/battery - معلومات البطارية\n"
        "/network - معلومات Wi-Fi\n"
        "/location - الموقع الحالي عبر GPS\n"
        "/ip - عنوان IP المحلي والعام\n"
        "/record - بدأ التسجيل الصوتي\n"
        "/stop - إيقاف التسجيل وإرساله\n"
        "/sms <رقم> <نص> - إرسال رسالة SMS\n"
        "/status - حالة البوت\n"
        "/help - إظهار هذه الرسالة\n"
    )
    bot.reply_to(message, text)
    logger.info("تم عرض قائمة الأوامر للمستخدم %s", message.from_user.id)


# ================== /status ==================
@bot.message_handler(commands=["status"])
def bot_status(message):
    if not is_admin(message):
        return

    status = (
        "🟢 حالة البوت: يعمل\n"
        f"👤 المسؤول: {ADMIN_ID}\n"
        f"📄 سجل التشغيل: {LOG_FILE}\n"
        f"🕐 الوقت: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    bot.reply_to(message, status)
    logger.info("تم طلب حالة البوت من المستخدم %s", message.from_user.id)


# ================== /ip ==================
@bot.message_handler(commands=["ip"])
def get_ip(message):
    if not is_admin(message):
        return

    try:
        wifi_result = subprocess.run(
            ["termux-wifi-connectioninfo"],
            capture_output=True,
            text=True,
            timeout=10
        )
        wifi = json.loads(wifi_result.stdout) if wifi_result.stdout.strip() else {}
        local_ip = wifi.get("ip", "غير متاح")

        public_result = subprocess.run(
            ["curl", "-4", "-sS", "--max-time", "10", "https://api.ipify.org"],
            capture_output=True,
            text=True,
            timeout=12,
            check=True
        )
        public_ip = public_result.stdout.strip() or "تعذر تحديده"

        bot.reply_to(message, f"📱 IP المحلي: {local_ip}\n🌍 IP العام: {public_ip}")
        logger.info("تم جلب IP للمستخدم %s", message.from_user.id)

    except Exception as e:
        logger.exception("فشل في جلب IP")
        bot.reply_to(message, f"❌ تعذر جلب عنوان IP:\n{e}")


# ================== /selfie و /photo ==================
@bot.message_handler(commands=["selfie", "photo"])
def handle_photo_request(message):
    if not is_admin(message):
        return

    command = message.text.split()[0].split("@")[0].lower()
    camera_id = "1" if command == "/selfie" else "0"
    camera_name = "الأمامية" if camera_id == "1" else "الخلفية"

    bot.reply_to(message, f"جاري التقاط الصورة بالكاميرا {camera_name}...")
    photo_path = Path(os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp")) / f"mybot_photo_{camera_id}.jpg"

    try:
        result = run_termux_command(["termux-camera-photo", "-c", camera_id, str(photo_path)])

        if result.startswith("خطأ:") or not photo_path.exists() or photo_path.stat().st_size == 0:
            bot.reply_to(message, "فشل التقاط الصورة. تحقق من أذونات الكاميرا وتطبيق Termux:API.")
            logger.warning("فشل التقاط صورة من الكاميرا %s", camera_name)
            return

        with open(photo_path, "rb") as photo:
            bot.send_photo(message.chat.id, photo, caption=f"تم التقاط الصورة بالكاميرا {camera_name}.")
        logger.info("تم التقاط صورة بالكاميرا %s للمستخدم %s", camera_name, message.from_user.id)

    except Exception as e:
        logger.exception("خطأ في التقاط الصورة")
        bot.reply_to(message, "تعذر التقاط الصورة أو إرسالها.")

    finally:
        if photo_path.exists():
            try:
                photo_path.unlink()
            except OSError as e:
                logger.warning("فشل حذف ملف الصورة: %s", e)


# ================== /battery ==================
@bot.message_handler(commands=["battery"])
def get_battery_info(message):
    if not is_admin(message):
        return

    output = run_termux_command(["termux-battery-status"])
    data = parse_json_output(output)

    if not isinstance(data, dict):
        bot.reply_to(message, "تعذر قراءة بيانات البطارية. تحقق من Termux:API.")
        logger.warning("تعذر قراءة بطارية: %s", output)
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
    logger.info("تم جلب معلومات البطارية للمستخدم %s", message.from_user.id)


# ================== /network ==================
@bot.message_handler(commands=["network"])
def get_network_info(message):
    if not is_admin(message):
        return

    output = run_termux_command(["termux-wifi-connectioninfo"])
    data = parse_json_output(output)

    if not isinstance(data, dict):
        bot.reply_to(message, "تعذر قراءة معلومات الشبكة. تحقق من Termux:API.")
        logger.warning("تعذر قراءة شبكة: %s", output)
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
    logger.info("تم جلب معلومات الشبكة للمستخدم %s", message.from_user.id)


# ================== /location ==================
@bot.message_handler(commands=["location"])
def get_location(message):
    if not is_admin(message):
        return

    best_location = None

    for attempt in range(3):
        try:
            result = subprocess.run(
                ["termux-location", "-p", "gps", "-r", "once"],
                capture_output=True,
                text=True,
                timeout=20
            )

            if result.returncode != 0:
                continue

            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                continue

            lat = data.get("latitude")
            lon = data.get("longitude")
            accuracy = data.get("accuracy")

            if lat is None or lon is None or accuracy is None:
                continue

            candidate = {"latitude": lat, "longitude": lon, "accuracy": float(accuracy)}

            if best_location is None or candidate["accuracy"] < best_location["accuracy"]:
                best_location = candidate

            if candidate["accuracy"] <= 20:
                break

        except Exception:
            pass

        if attempt < 2:
            time.sleep(2)

    if best_location is None:
        bot.reply_to(message, "❌ تعذر الحصول على موقع GPS صالح.\nتأكد من تفعيل الموقع وصلاحية Termux:API.")
        logger.warning("لم يتم الحصول على موقع GPS للمستخدم %s", message.from_user.id)
        return

    lat = best_location["latitude"]
    lon = best_location["longitude"]
    accuracy = best_location["accuracy"]

    maps_url = f"https://maps.google.com/?q={lat},{lon}"
    bot.reply_to(
        message,
        f"📍 موقع الهاتف\nخط العرض: {lat}\nخط الطول: {lon}\n"
        f"🎯 الدقة المقدرة: ±{accuracy:.1f} متر\n🗺️ الخريطة: {maps_url}"
    )

    logger.info("تم جلب موقع GPS للمستخدم %s", message.from_user.id)


# ================== /record و /stop ==================
@bot.message_handler(commands=["record"])
def start_recording(message):
    global RECORDING_FILE

    if not is_admin(message):
        return

    if RECORDING_FILE is not None:
        bot.reply_to(message, "⚠️ التسجيل يعمل بالفعل. أرسل /stop لإنهائه.")
        return

    file_path = RECORDING_DIR / ("recording_" + time.strftime("%Y%m%d_%H%M%S") + ".m4a")

    try:
        result = subprocess.run(
            ["termux-microphone-record", "-f", str(file_path), "-l", "0", "-e", "aac"],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            bot.reply_to(message, "❌ تعذر بدء التسجيل.\n" + detail[:800])
            logger.warning("فشل بدء التسجيل: %s", detail)
            return

        RECORDING_FILE = file_path
        bot.reply_to(message, "🎙️ بدأ التسجيل الصوتي.\nأرسل /stop لإيقافه وإرسال الملف.")
        logger.info("بدأ تسجيل صوتي للمستخدم %s", message.from_user.id)

    except Exception as e:
        RECORDING_FILE = None
        logger.exception("خطأ في بدء التسجيل")
        bot.reply_to(message, f"❌ خطأ في بدء التسجيل: {e}")


@bot.message_handler(commands=["stop"])
def stop_recording(message):
    global RECORDING_FILE

    if not is_admin(message):
        return

    if RECORDING_FILE is None:
        bot.reply_to(message, "ℹ️ لا يوجد تسجيل نشط.")
        return

    path = RECORDING_FILE
    result = None

    try:
        result = subprocess.run(
            ["termux-microphone-record", "-q"],
            capture_output=True,
            text=True,
            timeout=20
        )

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            bot.reply_to(message, "❌ تعذر إيقاف التسجيل بأمان.\n" + detail[:800])
            logger.warning("فشل إيقاف التسجيل: %s", detail)
            return

        time.sleep(1)

        if not path.exists() or path.stat().st_size < 100:
            bot.reply_to(message, "❌ ملف التسجيل فارغ أو غير موجود.")
            logger.warning("ملف التسجيل فارغ أو غير موجود: %s", path)
            return

        bot.reply_to(message, "📤 جارٍ إرسال التسجيل...")
        with open(path, "rb") as audio_file:
            bot.send_audio(message.chat.id, audio_file, title="تسجيل صوتي")
        logger.info("تم إرسال التسجيل الصوتي للمستخدم %s", message.from_user.id)

    except Exception as e:
        logger.exception("خطأ أثناء إيقاف التسجيل")
        bot.reply_to(message, f"❌ حدث خطأ: {e}")

    finally:
        if result is not None and result.returncode == 0:
            RECORDING_FILE = None
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass


# ================== /sms ==================
@bot.message_handler(commands=["sms"])
def send_sms(message):
    if not is_admin(message):
        return

    text = message.text.strip()
    if not text:
        bot.reply_to(message, "❌ استخدم الأمر بالشكل التالي:\n/sms 966500000000 مرحبا")
        return

    # مثال: /sms 966500000000 مرحبا بالعالم
    # نأخذ ما بعد /sms
    command_body = text.split(maxsplit=1)
    if len(command_body) < 2:
        bot.reply_to(message, "❌ استخدم الأمر بالشكل التالي:\n/sms 966500000000 مرحبا")
        return

    phone_number = command_body[1].split(maxsplit=1)[0]
    sms_text = command_body[1].split(maxsplit=1)[1] if len(command_body[1].split(maxsplit=1)) > 1 else ""

    if not phone_number or not sms_text:
        bot.reply_to(message, "❌ استخدم الأمر بالشكل التالي:\n/sms 966500000000 مرحبا")
        return

    # تنظيف الرقم
    phone_number = re.sub(r"\s+", "", phone_number)
    sms_text = sms_text.strip()

    try:
        result = subprocess.run(
            ["termux-sms-send", "-n", phone_number, sms_text],
            capture_output=True,
            text=True,
            timeout=20
        )

        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            bot.reply_to(message, "❌ تعذر إرسال الرسالة SMS.\n" + detail[:800])
            logger.warning("فشل إرسال SMS إلى %s: %s", phone_number, detail)
            return

        bot.reply_to(message, f"✅ تم إرسال رسالة SMS إلى {phone_number}")
        logger.info("تم إرسال SMS إلى %s من المستخدم %s", phone_number, message.from_user.id)

    except FileNotFoundError:
        bot.reply_to(message, "❌ أمر termux-sms-send غير موجود. تأكد من تثبيت Termux:API ودعم SMS.")
        logger.error("termux-sms-send غير موجود")
    except Exception as e:
        logger.exception("خطأ في إرسال SMS")
        bot.reply_to(message, f"❌ حدث خطأ أثناء إرسال SMS:\n{e}")


# ================== التعامل مع الرسائل غير المعروفة ==================
@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    # تجاهل الرسائل الفارغة أو الأوامر المعروفة
    if message.text and message.text.startswith("/"):
        logger.info("أمر غير معروف: %s من المستخدم %s", message.text, message.from_user.id if message.from_user else "unknown")
    return


# ================== تشغيل البوت ==================
if __name__ == "__main__":
    logger.info("البوت بدأ التشغيل...")
    print("البوت يعمل الآن...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20, skip_pending=False)
        except requests.exceptions.ReadTimeout:
            logger.warning("انتهت مهلة الاتصال، سيتم إعادة المحاولة.")
            time.sleep(5)
        except requests.exceptions.RequestException as e:
            logger.exception("خطأ اتصال: %s", e)
            time.sleep(10)
        except Exception as e:
            logger.exception("خطأ غير متوقع في البوت: %s", e)
            time.sleep(5)
