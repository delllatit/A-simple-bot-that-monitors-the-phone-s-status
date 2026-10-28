import os
import re
import json
import time
import html
import functools
import logging
import requests
import subprocess
import threading
import datetime
from pathlib import Path
import telebot
from dotenv import load_dotenv

# ================== تحميل .env ==================
# هذا يقرأ الملف .env الموجود في نفس المجلد
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_ID", "").strip()
# دعم قائمة مسؤولين متعددة مفصولة بفواصل: ADMIN_ID="123,456"
ADMIN_IDS = {int(x) for x in re.split(r"[,\s]+", ADMIN_IDS_RAW) if x.strip().lstrip("-").isdigit()}
LOG_FILE = os.getenv("BOT_LOG_FILE", str(Path.home() / "bot-logs" / "mybot.log"))
BATTERY_CHECK_INTERVAL = int(os.getenv("BATTERY_CHECK_INTERVAL", "1800"))  # ثوانٍ (افتراضي 30 دقائق)

# ================== إعدادات السجل ==================
LOG_DIR = Path(LOG_FILE).parent
LOG_DIR.mkdir(parents=True, exist_ok=True)
from logging.handlers import RotatingFileHandler

# هاندلر الملف: يسجل بس من مستوى WARNING وفوق (يعني ERROR, CRITICAL)
file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=1_000_000,
    backupCount=3,
    encoding="utf-8"
)
file_handler.setLevel(logging.WARNING)

# هاندلر الشاشة: يبين كل شي أثناء التشغيل المباشر (اختياري تخليه INFO)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,  # المستوى العام (أقل حد بين الاثنين)
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger("telegram_bot")

if not BOT_TOKEN:
    raise SystemExit("❌ لم يتم العثور على TELEGRAM_BOT_TOKEN داخل ملف .env أو البيئة.")
if not ADMIN_IDS:
    raise SystemExit("❌ قيمة ADMIN_ID غير صحيحة أو فارغة. يجب أن تكون رقمًا مثل: 6002823280 (أو قائمة مفصولة بفواصل)")

bot = telebot.TeleBot(BOT_TOKEN)

# ================== الإعدادات العامة ==================
RECORDING_FILE = None
RECORDING_LOCK = threading.Lock()  # لمنع حالة السباق بين /record و /stop
RECORDING_DIR = Path.home() / "bot-logs"
RECORDING_DIR.mkdir(parents=True, exist_ok=True)

# ================== متغيرات الوقت والتنبيهات ==================
BOT_START_TIME = datetime.datetime.now()
BATTERY_THRESHOLDS = [60, 50, 40, 30]
alerted_thresholds = set()

RATE_LIMIT_WINDOW = 3  # ثوانٍ بين الطلبات المتتالية لنفس المستخدم
rate_limit_state = {}
rate_limit_lock = threading.Lock()

# ================== الوظائف المساعدة ==================
def is_admin(message):
    return bool(message.from_user) and message.from_user.id in ADMIN_IDS

def admin_only(func):
    """Decorator للتحقق من صلاحيات المسؤول + حد عدد الطلبات، بدلاً من تكرار الفحص."""
    @functools.wraps(func)
    def wrapper(message, *args, **kwargs):
        if not is_admin(message):
            uid = getattr(message.from_user, "id", "unknown")
            logger.warning("محاولة وصول غير مصرح بها من المستخدم %s", uid)
            try:
                bot.reply_to(message, "🚫 عذراً، هذا البوت خاص بالمسؤول فقط.")
            except Exception:
                pass  # لا نفشل المعالجة إذا تعذر إرسال الرد
            return

        # حد عدد الطلبات (Rate Limiting) لتجنب الإغراق
        now = time.monotonic()
        with rate_limit_lock:
            last = rate_limit_state.get(message.from_user.id, 0)
            if now - last < RATE_LIMIT_WINDOW:
                return
            rate_limit_state[message.from_user.id] = now

        try:
            return func(message, *args, **kwargs)
        except telebot.apihelper.ApiTelegramException as e:
            logger.exception("خطأ في Telegram API أثناء معالجة الأمر: %s", e)
            try:
                bot.reply_to(message, "❌ حدث خطأ أثناء تنفيذ الأمر.")
            except Exception:
                pass
    return wrapper

def safe_send(chat_id, text, **kwargs):
    """إرسال رسالة مع تسجيل الأخطاء بصمت بدلاً من إسقاطها."""
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error("فشل إرسال تنبيه إلى %s: %s", chat_id, e)
        return None

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

# ================== مراقبة البطارية في الخلفية ==================
def battery_monitor():
    while True:
        try:
            result = subprocess.run(
                ["termux-battery-status"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                percentage = data.get("percentage")
                if percentage is not None:
                    # التحقق من عتبات التنبيه
                    for threshold in BATTERY_THRESHOLDS:
                        if percentage < threshold and threshold not in alerted_thresholds:
                            for admin_id in ADMIN_IDS:
                                safe_send(
                                    admin_id,
                                    f"⚠️ <b>تنبيه البطارية:</b>\nالنسبة الحالية: {percentage}%\n(وصلت إلى أقل من {threshold}%)",
                                    parse_mode="HTML"
                                )
                            alerted_thresholds.add(threshold)

                    # إعادة تعيين التنبيهات إذا تم الشحن فوق 60%
                    if percentage >= 60:
                        alerted_thresholds.clear()
        except Exception as e:
            logger.error(f"خطأ في مراقبة البطارية: {e}")

        # فحص البطارية كل BATTERY_CHECK_INTERVAL ثانية (افتراضي 5 دقائق)
        time.sleep(BATTERY_CHECK_INTERVAL)

# ================== /start و /help ==================
@bot.message_handler(commands=["start", "help"])
@admin_only
def send_welcome(message):
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
        "/sms رقم نص - إرسال رسالة SMS\n"
        "/uptime - مدة تشغيل البوت\n"
        "/status - حالة البوت\n"
        "/admins - قائمة المسؤولين المعتمدين\n"
        "/help - إظهار هذه الرسالة\n\n"
        "🔔 ملاحظة: تنبيهات البطارية تعمل تلقائياً عند 60%, 50%, 40%, 30%"
    )
    bot.reply_to(message, text)
    logger.info("تم عرض قائمة الأوامر للمستخدم %s", message.from_user.id)
# ================== /uptime ==================
@bot.message_handler(commands=["uptime"])
@admin_only
def get_uptime(message):
    now = datetime.datetime.now()
    delta = now - BOT_START_TIME

    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    uptime_str = ""
    if days > 0:
        uptime_str += f"{days} يوم، "
    uptime_str += f"{hours} ساعة، {minutes} دقيقة، {seconds} ثانية"

    bot.reply_to(message, f"⏳ <b>مدة تشغيل البوت:</b>\n{uptime_str}", parse_mode="HTML")
    logger.info("تم طلب مدة التشغيل من المستخدم %s", message.from_user.id)

# ================== /status ==================
@bot.message_handler(commands=["status"])
@admin_only
def bot_status(message):
    status = (
        "🟢 حالة البوت: يعمل\n"
        f"👤 المسؤولون: {', '.join(map(str, sorted(ADMIN_IDS)))}\n"
        f"📄 سجل التشغيل: {LOG_FILE}\n"
        f"🕐 الوقت: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    bot.reply_to(message, status)
    logger.info("تم طلب حالة البوت من المستخدم %s", message.from_user.id)

# ================== /admins ==================
@bot.message_handler(commands=["admins"])
@admin_only
def list_admins(message):
    """عرض قائمة المسؤولين المعتمدين في البوت."""
    if not ADMIN_IDS:
        msg = "⚠️ لا يوجد مسؤولون معتمدون! تأكد من ضبط متغير ADMIN_ID."
    else:
        admins_list = "\n".join(f"• <code>{aid}</code>" for aid in sorted(ADMIN_IDS))
        msg = (
            f"👥 <b>المسؤولون المعتمدون ({len(ADMIN_IDS)}):</b>\n{admins_list}\n\n"
            "➕ للإضافة: عدّل ADMIN_ID في ~/.bashrc أو .env بفواصل بين المعرفات،\n"
            "ثم نفّذ: source ~/.bashrc وأعد تشغيل البوت."
        )
    bot.reply_to(message, msg, parse_mode="HTML")
    logger.info("تم عرض قائمة المسؤولين للمستخدم %s", message.from_user.id)

# ================== /ip ==================
@bot.message_handler(commands=["ip"])
@admin_only
def get_ip(message):
    try:
        wifi_result = subprocess.run(
            ["termux-wifi-connectioninfo"],
            capture_output=True,
            text=True,
            timeout=10
        )
        wifi = json.loads(wifi_result.stdout) if wifi_result.stdout.strip() else {}
        local_ip = wifi.get("ip", "غير متاح")

        # استبدال curl بمكتبة requests مباشرة (أسرع ولا يحتاج عملية خارجية)
        resp = requests.get("https://api.ipify.org", timeout=10)
        resp.raise_for_status()
        public_ip = resp.text.strip() or "تعذر تحديده"

        bot.reply_to(message, f"📱 IP المحلي: {local_ip}\n🌍 IP العام: {public_ip}")
        logger.info("تم جلب IP للمستخدم %s", message.from_user.id)
    except Exception as e:
        logger.exception("فشل في جلب IP")
        bot.reply_to(message, f"❌ تعذر جلب عنوان IP:\n{e}")

# ================== /selfie و /photo ==================
@bot.message_handler(commands=["selfie", "photo"])
@admin_only
def handle_photo_request(message):
    command = (message.text or "").split()[0].split("@")[0].lower()
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
@admin_only
def get_battery_info(message):
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
@admin_only
def get_network_info(message):
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
def fetch_gps_location(message):
    """تحديد الموقع في خيط منفصل حتى لا يُحظر الـ Polling أثناء محاولة الـ GPS."""
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
        safe_send(message.chat.id, "❌ تعذر الحصول على موقع GPS صالح.\nتأكد من تفعيل الموقع وصلاحية Termux:API.")
        logger.warning("لم يتم الحصول على موقع GPS للمستخدم %s", message.from_user.id)
        return

    lat = best_location["latitude"]
    lon = best_location["longitude"]
    accuracy = best_location["accuracy"]
    maps_url = f"https://maps.google.com/?q={lat},{lon}"

    safe_send(
        message.chat.id,
        f"📍 موقع الهاتف\nخط العرض: {lat}\nخط الطول: {lon}\n"
        f"🎯 الدقة المقدرة: ±{accuracy:.1f} متر\n🗺️ الخريطة: {maps_url}"
    )
    logger.info("تم جلب موقع GPS للمستخدم %s", message.from_user.id)

@bot.message_handler(commands=["location"])
@admin_only
def get_location(message):
    threading.Thread(target=fetch_gps_location, args=(message,), daemon=True).start()

# ================== /record و /stop ==================
@bot.message_handler(commands=["record"])
@admin_only
def start_recording(message):
    global RECORDING_FILE

    with RECORDING_LOCK:
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
                return  # RECORDING_FILE يبقى None تلقائياً عند الفشل

            RECORDING_FILE = file_path
            bot.reply_to(message, "🎙️ بدأ التسجيل الصوتي.\nأرسل /stop لإيقافه وإرسال الملف.")
            logger.info("بدأ تسجيل صوتي للمستخدم %s", message.from_user.id)
        except Exception as e:
            RECORDING_FILE = None
            logger.exception("خطأ في بدء التسجيل")
            bot.reply_to(message, f"❌ خطأ في بدء التسجيل: {e}")

@bot.message_handler(commands=["stop"])
@admin_only
def stop_recording(message):
    global RECORDING_FILE

    with RECORDING_LOCK:
        if RECORDING_FILE is None:
            bot.reply_to(message, "ℹ️ لا يوجد تسجيل نشط.")
            return
        path = RECORDING_FILE
        RECORDING_FILE = None  # تصفير الحالة فوراً لمنع تعليق البوت أو إيقاف مزدوج

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
        # حذف الملف الحساس بعد الإرسال أو المحاولة
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

# ================== /sms ==================
@bot.message_handler(commands=["sms"])
@admin_only
def send_sms(message):
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "❌ استخدم الأمر بالشكل التالي:\n/sms 966500000000 مرحبا")
        return

    phone_number = re.sub(r"\s+", "", parts[1])
    sms_text = parts[2].strip()

    # التحقق من صحة رقم الهاتف قبل الإرسال (7-15 رقماً، يبدأ بـ + أو أرقام)
    if not re.fullmatch(r"\+?\d{7,15}", phone_number) or not sms_text:
        bot.reply_to(message, "❌ رقم هاتف غير صالح. استخدم الصيغة الدولية مثل: 9665XXXXXXXX")
        return

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
@bot.message_handler(content_types=["text"])
def handle_unknown(message):
    if message.text and message.text.startswith("/"):
        logger.info("أمر غير معروف: %s من المستخدم %s", message.text, message.from_user.id if message.from_user else "unknown")
        bot.reply_to(message, "❓ أمر غير معروف. أرسل /help لعرض القائمة.")

# ================== تشغيل البوت ==================
if __name__ == "__main__":
    logger.info("البوت بدأ التشغيل...")
    print("البوت يعمل الآن...")

    # تسجيل قائمة الأوامر في Telegram (تظهر تلقائياً بدون أزرار)
    try:
        bot.set_my_commands([
            telebot.types.BotCommand("selfie", "تصوير بالكاميرا الأمامية"),
            telebot.types.BotCommand("photo", "تصوير بالكاميرا الخلفية"),
            telebot.types.BotCommand("battery", "معلومات البطارية"),
            telebot.types.BotCommand("network", "معلومات Wi-Fi"),
            telebot.types.BotCommand("location", "الموقع الحالي عبر GPS"),
            telebot.types.BotCommand("ip", "عنوان IP المحلي والعام"),
            telebot.types.BotCommand("record", "بدء التسجيل الصوتي"),
            telebot.types.BotCommand("stop", "إيقاف التسجيل وإرساله"),
            telebot.types.BotCommand("sms", "إرسال رسالة SMS"),
            telebot.types.BotCommand("uptime", "مدة تشغيل البوت"),
            telebot.types.BotCommand("status", "حالة البوت"),
            telebot.types.BotCommand("admins", "قائمة المسؤولين المعتمدين"),
            telebot.types.BotCommand("help", "إظهار قائمة الأوامر"),
        ])
    except Exception as e:
        logger.warning("تعذر تسجيل قائمة الأوامر: %s", e)

    # تشغيل خيط مراقبة البطارية في الخلفية
    monitor_thread = threading.Thread(target=battery_monitor, daemon=True)
    monitor_thread.start()

    backoff = 5  # تراجع تصاعدي لإعادة الاتصال
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20, skip_pending=True)
            backoff = 5  # إعادة ضبط التراجع عند انتهاء طبيعي
        except requests.exceptions.ReadTimeout:
            logger.warning("انتهت مهلة الاتصال، سيتم إعادة المحاولة.")
            time.sleep(min(backoff, 60))
        except requests.exceptions.RequestException as e:
            logger.exception("خطأ اتصال: %s", e)
            time.sleep(min(backoff, 60))
            backoff = min(backoff * 2, 300)  # مضاعفة الانتظار حتى 5 دقائق كحد أقصى
        except Exception as e:
            logger.exception("خطأ غير متوقع في البوت: %s", e)
            time.sleep(min(backoff, 60))
            backoff = min(backoff * 2, 300)
