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
import atexit       # NEW
import signal       # NEW
import shutil
from pathlib import Path
import telebot
from dotenv import load_dotenv

# ================== تحميل .env ==================
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_IDS = {int(x) for x in re.split(r"[,\s]+", ADMIN_IDS_RAW) if x.strip().lstrip("-").isdigit()}
LOG_FILE = os.getenv("BOT_LOG_FILE", str(Path.home() / "bot-logs" / "mybot.log"))
BATTERY_CHECK_INTERVAL = int(os.getenv("BATTERY_CHECK_INTERVAL", "1800"))

# ================== إعدادات السجل ==================
LOG_DIR = Path(LOG_FILE).parent
LOG_DIR.mkdir(parents=True, exist_ok=True)
from logging.handlers import RotatingFileHandler

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=1_000_000,
    backupCount=3,
    encoding="utf-8"
)
file_handler.setLevel(logging.WARNING)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
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
RECORDING_LOCK = threading.Lock()
RECORDING_DIR = Path.home() / "bot-logs"
RECORDING_DIR.mkdir(parents=True, exist_ok=True)

# NEW: حدث الإيقاف النظيف (يُشارَك بين الخيوط)
SHUTDOWN = threading.Event()

# NEW: تنظيف التسجيل النشط (idempotent - آمن للاستدعاء المتكرر)
def _cleanup_recording():
    """يوقف أي تسجيل نشط ويحذف الملف الحساس."""
    global RECORDING_FILE
    with RECORDING_LOCK:
        path = RECORDING_FILE
        RECORDING_FILE = None
    if path is None:
        return
    try:
        subprocess.run(
            ["termux-microphone-record", "-q"],
            capture_output=True, timeout=10
        )
    except Exception as e:
        logger.warning("تعذر إيقاف التسجيل عند التنظيف: %s", e)
    if path.exists():
        try:
            path.unlink()
            logger.info("تم حذف ملف التسجيل المعلق: %s", path)
        except OSError as e:
            logger.warning("فشل حذف ملف التسجيل: %s", e)

# NEW: تنظيف عند الإقلاع — يعالج الحالة التي انهار فيها البوت سابقًا (kill -9)
def _cleanup_orphan_recordings():
    """يوقف أي تسجيل شغّال من جلسة سابقة ويحذف ملفات تسجيل يتيمة."""
    try:
        subprocess.run(
            ["termux-microphone-record", "-q"],
            capture_output=True, timeout=10
        )
    except Exception:
        pass
    cutoff = time.time() - 3600
    for f in RECORDING_DIR.glob("recording_*.m4a"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                logger.info("حذف ملف تسجيل يتيم: %s", f)
        except OSError:
            pass

# NEW: معالج إشارات SIGTERM / SIGINT
def _signal_handler(signum, frame):
    logger.info("تم استلام إشارة %s، بدء الإيقاف النظيف...", signum)
    SHUTDOWN.set()
    try:
        bot.stop_polling()
    except Exception:
        pass

# ================== متغيرات الوقت والتنبيهات ==================
BOT_START_TIME = datetime.datetime.now()
BATTERY_THRESHOLDS = [60, 50, 40, 30]
alerted_thresholds = set()
battery_api_warned = False  # NEW: لمنع تكرار تنبيه عدم توفر termux-api

RATE_LIMIT_WINDOW = 3
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
                pass
            return

        now = time.monotonic()
        with rate_limit_lock:
            last = rate_limit_state.get(message.from_user.id, 0)
            if now - last < RATE_LIMIT_WINDOW:
                return
            rate_limit_state[message.from_user.id] = now

        try:
            return func(message, *args, **kwargs)
        except telebot.apihelper.ApiTelegramException as e:
            # FIX: التفاصيل الكاملة في اللوج فقط — رسالة عامة للمستخدم (BOT_ERROR لا يُعاد إرساله عبر reply_to)
            logger.exception("خطأ في Telegram API أثناء معالجة الأمر: %s", e)
            try:
                if getattr(e, "error_code", None) != 429:
                    bot.reply_to(message, "❌ حدث خطأ أثناء الاتصال بـ Telegram. راجع سجل البوت.")
            except Exception:
                pass
        except Exception as e:
            # NEW: لا نبتلع الأخطاء غير المتوقعة بصمت
            logger.exception("خطأ غير متوقع في %s: %s", func.__name__, e)
            try:
                # FIX: عدم كشف نص الاستثناء للمستخدم (قد يحوي مسارات/بيانات حساسة)
                bot.reply_to(message, "❌ حدث خطأ غير متوقع. راجع سجل البوت.")
            except Exception:
                pass
    return wrapper

def safe_send(chat_id, text, **kwargs):
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
    global battery_api_warned  # NEW
    while not SHUTDOWN.is_set():  # MODIFIED (fix 6): بدل while True
        try:
            result = subprocess.run(
                ["termux-battery-status"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                battery_api_warned = False  # NEW: إعادة الضبط عند النجاح
                data = json.loads(result.stdout)
                percentage = data.get("percentage")
                if percentage is not None:
                    for threshold in BATTERY_THRESHOLDS:
                        if percentage < threshold and threshold not in alerted_thresholds:
                            for admin_id in ADMIN_IDS:
                                safe_send(
                                    admin_id,
                                    f"⚠️ <b>تنبيه البطارية:</b>\nالنسبة الحالية: {percentage}%\n(وصلت إلى أقل من {threshold}%)",
                                    parse_mode="HTML"
                                )
                            alerted_thresholds.add(threshold)

                    # MODIFIED (fix 1): هامش 5% لمنع الوميض حول العتبة
                    if percentage >= 65:
                        alerted_thresholds.clear()
        except FileNotFoundError:
            # NEW (fix 5): تنبيه مرة واحدة إذا كان termux-api غير مثبت
            if not battery_api_warned:
                battery_api_warned = True
                for admin_id in ADMIN_IDS:
                    safe_send(
                        admin_id,
                        "⚠️ termux-api غير مثبت أو termux-battery-status غير متاح. تنبيهات البطارية معطلة حتى إصلاح ذلك."
                    )
                logger.error("termux-battery-status غير موجود أو غير مثبت")
        except Exception as e:
            logger.error(f"خطأ في مراقبة البطارية: {e}")

        SHUTDOWN.wait(BATTERY_CHECK_INTERVAL)  # MODIFIED (fix 6): بدل time.sleep

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
        "/help - إظهار هذه الرسالة\n"
        "/storage - مساحة القرص\n"          # NEW
        "/cpu - استخدام المعالج والذاكرة\n"  # NEW
        "/contacts - قائمة جهات الاتصال\n"   # NEW
        "/call رقم - إجراء مكالمة\n"         # NEW

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

        resp = requests.get("https://api.ipify.org", timeout=10)
        resp.raise_for_status()
        public_ip = resp.text.strip() or "تعذر تحديده"

        bot.reply_to(message, f"📱 IP المحلي: {local_ip}\n🌍 IP العام: {public_ip}")
        logger.info("تم جلب IP للمستخدم %s", message.from_user.id)
    except Exception as e:
        logger.exception("فشل في جلب IP")
        # FIX: التفاصيل في اللوج فقط
        bot.reply_to(message, "❌ تعذر جلب عنوان IP. راجع سجل البوت.")

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
RECORD_MAX_SECONDS = int(os.getenv("RECORD_MAX_SECONDS", "600"))  # حد أقصى افتراضي 10 دقائق

def _auto_stop_recording():
    """FIX: إيقاف تلقائي للتسجيل بعد RECORD_MAX_SECONDS لمنع التسجيل غير المحدود."""
    deadline = time.monotonic() + RECORD_MAX_SECONDS
    while time.monotonic() < deadline and not SHUTDOWN.is_set():
        time.sleep(1)
        with RECORDING_LOCK:
            if RECORDING_FILE is None:
                return  # تم إيقاف التسجيل يدوياً عبر /stop
    if SHUTDOWN.is_set():
        return
    with RECORDING_LOCK:
        path = RECORDING_FILE
        RECORDING_FILE = None
    if path is None:
        return
    logger.warning("تم إيقاف التسجيل تلقائياً بعد تجاوز الحد الأقصى (%d ثانية)", RECORD_MAX_SECONDS)
    try:
        subprocess.run(["termux-microphone-record", "-q"], capture_output=True, text=True, timeout=20)
        time.sleep(1)
        for admin_id in ADMIN_IDS:
            if path.exists() and path.stat().st_size >= 100:
                with open(path, "rb") as audio_file:
                    bot.send_audio(admin_id, audio_file, title="تسجيل صوتي (إيقاف تلقائي)")
            else:
                safe_send(admin_id, "⏹️ تم إيقاف التسجيل تلقائياً بعد تجاوز الحد الأقصى المسموح.")
    except Exception as e:
        logger.exception("فشل الإيقاف التلقائي/إرسال التسجيل: %s", e)
    finally:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

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
                # FIX: تحديد مدة قصوى للتسجيل بدل -l 0 غير المحدود
                ["termux-microphone-record", "-f", str(file_path), "-l", str(RECORD_MAX_SECONDS), "-e", "aac"],
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                # FIX: التفاصيل الكاملة تُسجَّل في اللوج فقط، ولا تُعرض للمستخدم
                bot.reply_to(message, "❌ تعذر بدء التسجيل. تحقق من أذونات الميكروفون وTermux:API.")
                logger.warning("فشل بدء التسجيل: %s", detail)
                return

            RECORDING_FILE = file_path
            bot.reply_to(message,
                         f"🎙️ بدأ التسجيل الصوتي.\nأرسل /stop لإيقافه وإرسال الملف.\n"
                         f"(إيقاف تلقائي بعد {RECORD_MAX_SECONDS // 60} دقيقة كحد أقصى)")
            logger.info("بدأ تسجيل صوتي للمستخدم %s", message.from_user.id)
            # FIX: مراقب للإيقاف التلقائي إذا لم يُرسَل /stop
            threading.Thread(target=_auto_stop_recording, daemon=True).start()
        except Exception as e:
            RECORDING_FILE = None
            logger.exception("خطأ في بدء التسجيل")
            bot.reply_to(message, "❌ حدث خطأ أثناء بدء التسجيل. راجع سجل البوت.")

@bot.message_handler(commands=["stop"])
@admin_only
def stop_recording(message):
    global RECORDING_FILE

    with RECORDING_LOCK:
        if RECORDING_FILE is None:
            bot.reply_to(message, "ℹ️ لا يوجد تسجيل نشط.")
            return
        path = RECORDING_FILE
        RECORDING_FILE = None

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
            # FIX: عدم كشف مخرجات النظام الخام للمستخدم
            bot.reply_to(message, "❌ تعذر إيقاف التسجيل بأمان. راجع سجل البوت.")
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
        bot.reply_to(message, "❌ حدث خطأ أثناء إيقاف التسجيل. راجع سجل البوت.")
    finally:
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
            # FIX: التفاصيل في اللوج فقط، رسالة عامة للمستخدم
            bot.reply_to(message, "❌ تعذر إرسال رسالة SMS. تحقق من أذونات Termux:API.")
            logger.warning("فشل إرسال SMS إلى %s: %s", phone_number, detail)
            return

        bot.reply_to(message, f"✅ تم إرسال رسالة SMS إلى {phone_number}")
        logger.info("تم إرسال SMS إلى %s من المستخدم %s", phone_number, message.from_user.id)
    except FileNotFoundError:
        bot.reply_to(message, "❌ أمر termux-sms-send غير موجود. تأكد من تثبيت Termux:API ودعم SMS.")
        logger.error("termux-sms-send غير موجود")
    except Exception as e:
        logger.exception("خطأ في إرسال SMS")
        bot.reply_to(message, "❌ حدث خطأ أثناء إرسال SMS. راجع سجل البوت.")

# ================== /storage ==================
@bot.message_handler(commands=["storage"])
@admin_only
def get_storage_info(message):
    """عرض مساحة القرص باستخدام مكتبة بايثون المدمجة (لا تحتاج df)."""
    try:
        targets = [str(Path.home())]
        shared = Path("/storage/emulated/0")
        if shared.exists():
            targets.append(str(shared))

        rows = []
        seen = set()

        for target in targets:
            if target in seen:
                continue
            seen.add(target)
            try:
                # استخدام shutil.disk_usage بدلاً من df
                usage = shutil.disk_usage(target)
            except Exception as e:
                logger.warning("فشل قراءة المساحة لـ %s: %s", target, e)
                continue

            total_gb = usage.total / (1024**3)
            used_gb = usage.used / (1024**3)
            free_gb = usage.free / (1024**3)
            percent = (usage.used / usage.total) * 100 if usage.total else 0

            rows.append(
                f"📂 <b>{html.escape(target)}</b>\n"
                f"   الكل: {total_gb:.2f} GB | المستخدم: {used_gb:.2f} GB\n"
                f"   المتاح: {free_gb:.2f} GB | النسبة: {percent:.1f}%"
            )

        if not rows:
            bot.reply_to(message, "❌ تعذر قراءة معلومات التخزين.")
            return

        report = "💾 <b>مساحة القرص:</b>\n\n" + "\n\n".join(rows)
        bot.reply_to(message, report, parse_mode="HTML")
        logger.info("تم جلب مساحة القرص للمستخدم %s", message.from_user.id)
    except Exception as e:
        logger.exception("خطأ في جلب مساحة القرص")
        bot.reply_to(message, "❌ حدث خطأ أثناء جلب معلومات التخزين. راجع سجل البوت.")

# ================== /cpu ==================
@bot.message_handler(commands=["cpu"])
@admin_only
def get_cpu_info(message):
    """FIX: تنفيذ أمر /cpu المفقود — عرض استخدام المعالج والذاكرة من /proc."""
    try:
        # --- حمل المعالج من /proc/loadavg ---
        load1 = load5 = load15 = "N/A"
        try:
            with open("/proc/loadavg", "r") as f:
                parts = f.read().split()
                load1, load5, load15 = parts[0], parts[1], parts[2]
        except OSError:
            pass

        cpu_count = os.cpu_count() or 1

        # --- نسبة الاستخدام من فرق قراءتين في /proc/stat ---
        cpu_percent = None
        try:
            def read_cpu_times():
                with open("/proc/stat", "r") as f:
                    fields = f.readline().split()[1:]
                values = [int(x) for x in fields]
                idle = values[3] + (values[4] if len(values) > 4 else 0)
                total = sum(values)
                return total, idle

            t1, i1 = read_cpu_times()
            time.sleep(0.5)
            t2, i2 = read_cpu_times()
            dt = t2 - t1
            if dt > 0:
                cpu_percent = (1 - (i2 - i1) / dt) * 100
        except OSError:
            pass

        # --- الذاكرة من /proc/meminfo ---
        mem_total_kb = mem_avail_kb = None
        swap_total_kb = swap_free_kb = None
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    key, _, val = line.partition(":")
                    num = val.strip().split(" ")[0]
                    if not num.isdigit():
                        continue
                    if key == "MemTotal":
                        mem_total_kb = int(num)
                    elif key == "MemAvailable":
                        mem_avail_kb = int(num)
                    elif key == "SwapTotal":
                        swap_total_kb = int(num)
                    elif key == "SwapFree":
                        swap_free_kb = int(num)
        except OSError:
            pass

        lines = ["🖥️ <b>حالة المعالج والذاكرة:</b>", ""]
        cpu_line = f"- <b>الحمل (1/5/15 دقيقة):</b> {load1} / {load5} / {load15} ({cpu_count} نواة)"
        if cpu_percent is not None:
            cpu_line += f"\n- <b>استخدام المعالج:</b> {cpu_percent:.1f}%"
        lines.append(cpu_line)

        if mem_total_kb and mem_avail_kb is not None:
            used_mb = (mem_total_kb - mem_avail_kb) / 1024
            total_mb = mem_total_kb / 1024
            pct = (used_mb / total_mb * 100) if total_mb else 0
            lines.append(f"- <b>الذاكرة المستخدمة:</b> {used_mb:.0f} MB من {total_mb:.0f} MB ({pct:.1f}%)")
        else:
            lines.append("- <b>الذاكرة:</b> غير متاحة")

        if swap_total_kb:
            swap_used_mb = (swap_total_kb - (swap_free_kb or 0)) / 1024
            lines.append(f"- <b>Swap:</b> {swap_used_mb:.0f} MB من {swap_total_kb / 1024:.0f} MB")

        # --- عدد العمليات ---
        try:
            proc_count = sum(1 for p in Path("/proc").iterdir() if p.name.isdigit())
            lines.append(f"- <b>عدد العمليات:</b> {proc_count}")
        except OSError:
            pass

        bot.reply_to(message, "\n".join(lines), parse_mode="HTML")
        logger.info("تم جلب معلومات المعالج للمستخدم %s", message.from_user.id)
    except Exception as e:
        logger.exception("خطأ في جلب معلومات المعالج")
        bot.reply_to(message, "❌ حدث خطأ أثناء جلب معلومات المعالج. راجع سجل البوت.")

# ================== /contacts =================
@bot.message_handler(commands=["contacts"])
@admin_only
def get_contacts(message):
    """عرض جهات الاتصال (بحد أقصى 100 لتجنب الرسائل الضخمة)."""
    try:
        # 1. تحديد مسار الأمر بدقة (لتفادي مشكلة tmux)
        termux_prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
        cmd_path = Path(termux_prefix) / "bin" / "termux-contact-list"

        # إذا لم يكن الملف موجوداً، نستخدم الأمر العادي كخيار أخير
        cmd = str(cmd_path) if cmd_path.exists() else "termux-contact-list"

        result = subprocess.run(
            [cmd],
            capture_output=True, text=True, timeout=30
        )

        # 2. إذا فشل الأمر، تُسجَّل التفاصيل في اللوج فقط (FIX: عدم كشف مخرجات النظام)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            bot.reply_to(message, "❌ تعذر قراءة جهات الاتصال. تأكد من أذونات Termux:API.")
            logger.warning("فشل termux-contact-list (كود %s): %s", result.returncode, detail)
            return

        if not result.stdout.strip():
            bot.reply_to(message, "❌ الأمر نُفذ بنجاح لكن النتيجة فارغة! تأكد من منح تطبيق Termux:API إذن جهات الاتصال.")
            return

        try:
            contacts = json.loads(result.stdout)
        except json.JSONDecodeError:
            # FIX: لا نرسل الناتج الخام للمستخدم — يُسجَّل في اللوج فقط
            bot.reply_to(message, "❌ تعذر تحليل بيانات جهات الاتصال. راجع سجل البوت.")
            logger.warning("JSON غير صالح من termux-contact-list: %s", result.stdout[:800])
            return

        if not isinstance(contacts, list):
            bot.reply_to(message, "❌ صيغة غير متوقعة من termux-contact-list.")
            return

        if not contacts:
            bot.reply_to(message, "📇 لا توجد جهات اتصال.")
            return

        MAX_CONTACTS = 100
        shown = contacts[:MAX_CONTACTS]
        lines = []
        for c in shown:
            if not isinstance(c, dict):
                continue
            name = c.get("name", "بدون اسم")
            number = c.get("number", "بدون رقم")
            lines.append(
                f"• <b>{html.escape(str(name))}</b>: <code>{html.escape(str(number))}</code>"
            )

        header = f"📇 <b>جهات الاتصال ({len(contacts)}):</b>"
        if len(contacts) > MAX_CONTACTS:
            header += f"\n(يتم عرض أول {MAX_CONTACTS} فقط)"

        report = header + "\n\n" + "\n".join(lines)
        if len(report) > 4000:
            report = report[:3900] + "\n..."
        bot.reply_to(message, report, parse_mode="HTML")
        logger.info("تم جلب جهات الاتصال (%d) للمستخدم %s", len(contacts), message.from_user.id)

    except FileNotFoundError:
        bot.reply_to(message, "❌ أمر termux-contact-list غير موجود. تأكد من تثبيت Termux:API.")
        logger.error("termux-contact-list غير موجود")
    except Exception as e:
        logger.exception("خطأ في جلب جهات الاتصال")
        bot.reply_to(message, "❌ حدث خطأ أثناء جلب جهات الاتصال. راجع سجل البوت.")

# ================== /call ==================
@bot.message_handler(commands=["call"])
@admin_only
def make_call(message):
    """بدء مكالمة عبر termux-telephony-call."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ استخدم الأمر بالشكل التالي:\n/call 966500000000")
        return

    phone_number = re.sub(r"\s+", "", parts[1])
    if not re.fullmatch(r"\+?\d{7,15}", phone_number):
        bot.reply_to(message, "❌ رقم هاتف غير صالح. استخدم الصيغة الدولية مثل: 9665XXXXXXXX")
        return

    try:
        result = subprocess.run(
            ["termux-telephony-call", phone_number],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            # FIX: التفاصيل في اللوج فقط، رسالة عامة للمستخدم
            bot.reply_to(message, "❌ تعذر إجراء المكالمة. تحقق من أذونات Termux:API.")
            logger.warning("فشل termux-telephony-call إلى %s: %s", phone_number, detail)
            return

        bot.reply_to(message, f"📞 تم بدء المكالمة إلى {phone_number}")
        logger.info("تم بدء مكالمة إلى %s من المستخدم %s", phone_number, message.from_user.id)
    except FileNotFoundError:
        bot.reply_to(message, "❌ أمر termux-telephony-call غير موجود. تأكد من تثبيت Termux:API.")
        logger.error("termux-telephony-call غير موجود")
    except Exception as e:
        logger.exception("خطأ في إجراء المكالمة")
        bot.reply_to(message, "❌ حدث خطأ أثناء إجراء المكالمة. راجع سجل البوت.")

# ================== التعامل مع الرسائل غير المعروفة ==================
# FIX: الديكوريتر كان مفقوداً/في موضع خاطئ سابقاً — الآن مسجّل بشكل صحيح
# ويأتي أخيراً ليلتقط فقط ما لم تلتقطه أوامر message_handler الأخرى
@bot.message_handler(content_types=["text"])
@admin_only
def handle_unknown(message):
    if message.text and message.text.startswith("/"):
        logger.info("أمر غير معروف: %s من المستخدم %s", message.text, message.from_user.id if message.from_user else "unknown")
        bot.reply_to(message, "❓ أمر غير معروف. أرسل /help لعرض القائمة.")
    # الرسائل النصية العادية تُتجاهل (البوت أوامري فقط)

# ================== تشغيل البوت ==================
if __name__ == "__main__":
    # NEW (fix 3): تنظيف التسجيلات اليتيمة من جلسة سابقة
    _cleanup_orphan_recordings()

    # NEW (fix 3 + 6): تسجيل handlers للتنظيف والإيقاف
    atexit.register(_cleanup_recording)
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    logger.info("البوت بدأ التشغيل...")
    print("البوت يعمل الآن...")

    try:
        # FIX: إزالة التكرار — sms كان مكررًا، وإضافة start الناقصة
        bot.set_my_commands([
            telebot.types.BotCommand("start", "بدء استخدام البوت وعرض الأوامر"),
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
            telebot.types.BotCommand("storage", "مساحة القرص"),
            telebot.types.BotCommand("cpu", "استخدام المعالج والذاكرة"),
            telebot.types.BotCommand("contacts", "قائمة جهات الاتصال"),
            telebot.types.BotCommand("call", "إجراء مكالمة"),
        ])
    except Exception as e:
        logger.warning("تعذر تسجيل قائمة الأوامر: %s", e)

    monitor_thread = threading.Thread(target=battery_monitor, daemon=True)
    monitor_thread.start()

    backoff = 5
    while not SHUTDOWN.is_set():  # MODIFIED (fix 6): بدل while True
        try:
            # FIX: كان skip_pending=True يتسبب في تجاهل اوامر معلقة اثناء انقطاع الاتصال
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
            backoff = 5
        except requests.exceptions.ReadTimeout:
            logger.warning("انتهت مهلة الاتصال، سيتم إعادة المحاولة.")
            SHUTDOWN.wait(min(backoff, 60))  # MODIFIED (fix 6)
        except requests.exceptions.RequestException as e:
            logger.exception("خطأ اتصال: %s", e)
            SHUTDOWN.wait(min(backoff, 60))  # MODIFIED (fix 6)
            backoff = min(backoff * 2, 300)
        except Exception as e:
            logger.exception("خطأ غير متوقع في البوت: %s", e)
            SHUTDOWN.wait(min(backoff, 60))  # MODIFIED (fix 6)
            backoff = min(backoff * 2, 300)
