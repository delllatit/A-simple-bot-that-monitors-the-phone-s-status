import telebot
import subprocess
import json
import os
import time
import requests
import html
from pathlib import Path

# ================== الإعدادات ==================
# يُفضل وضع التوكن والـ Admin ID في متغيرات بيئة (Environment Variables) للأمان
TOKEN = "ضع_التوكن_الجديد_هنا"
ADMIN_ID = 6002823280
# ===============================================

bot = telebot.TeleBot(TOKEN)

RECORDING_FILE = None
RECORDING_DIR = Path.home() / "bot-logs"
RECORDING_DIR.mkdir(parents=True, exist_ok=True)

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
        bot.reply_to(message, "عذراً، هذا البوت خاص بالمسؤول فقط.")
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
        "/location - جلب الموقع الحالي عبر GPS\n"
        "/ip - جلب عنوان IP\n"
        "/record - بدء التسجيل الصوتي\n"
        "/stop - إيقاف التسجيل وإرساله\n"
    )
    bot.reply_to(message, text)

# --- جلب IP ---
@bot.message_handler(commands=['ip'])
def get_ip(message):
    if not is_admin(message):
        return
    try:
        result = subprocess.run(
            ['termux-wifi-connectioninfo'],
            capture_output=True, text=True, timeout=10
        )
        wifi = json.loads(result.stdout)
        local_ip = wifi.get('ip', 'غير متاح')

        result = subprocess.run(
            ['curl', '-4', '-sS', '--max-time', '10', 'https://api.ipify.org'],
            capture_output=True, text=True, timeout=12, check=True
        )
        public_ip = result.stdout.strip() or 'تعذر تحديده'

        bot.reply_to(message, f"📱 IP المحلي: {local_ip}\n🌍 IP العام: {public_ip}")
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
        result = run_termux_command(["termux-camera-photo", "-c", camera_id, photo_path])
        if result.startswith("خطأ:") or not os.path.isfile(photo_path) or os.path.getsize(photo_path) == 0:
            bot.reply_to(message, "فشل التقاط الصورة. تحقق من أذونات الكاميرا وتطبيق Termux:API.")
            return

        with open(photo_path, "rb") as photo:
            bot.send_photo(message.chat.id, photo, caption=f"تم التقاط الصورة بالكاميرا {camera_name}.")
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
@bot.message_handler(commands=['location'])
def get_location(message):
    if not is_admin(message):
        return

    best_location = None
    for attempt in range(3):
        try:
            result = subprocess.run(
                ['termux-location', '-p', 'gps', '-r', 'once'],
                capture_output=True, text=True, timeout=20
            )
            if result.returncode != 0:
                continue

            data = json.loads(result.stdout)
            lat, lon, accuracy = data.get('latitude'), data.get('longitude'), data.get('accuracy')

            if lat is None or lon is None or accuracy is None:
                continue

            candidate = {'latitude': lat, 'longitude': lon, 'accuracy': float(accuracy)}
            if best_location is None or candidate['accuracy'] < best_location['accuracy']:
                best_location = candidate

            if candidate['accuracy'] <= 20:
                break
        except Exception:
            pass

        if attempt < 2:
            time.sleep(2)

    if best_location is None:
        bot.reply_to(message, '❌ تعذر الحصول على موقع GPS صالح.\nتأكد من تفعيل الموقع وصلاحية Termux:API.')
        return

    lat, lon, accuracy = best_location['latitude'], best_location['longitude'], best_location['accuracy']
    maps_url = f'https://maps.google.com/?q={lat},{lon}'
    bot.reply_to(
        message,
        f'📍 موقع الهاتف\nخط العرض: {lat}\nخط الطول: {lon}\n'
        f'🎯 الدقة المقدرة: ±{accuracy:.1f} متر\n🗺️ الخريطة: {maps_url}'
    )

# --- التسجيل الصوتي ---
@bot.message_handler(commands=['record'])
def start_recording(message):
    global RECORDING_FILE
    if not is_admin(message):
        return
    if RECORDING_FILE is not None:
        bot.reply_to(message, "⚠️ التسجيل يعمل بالفعل. أرسل /stop لإنهائه.")
        return

    path = RECORDING_DIR / ("recording_" + time.strftime("%Y%m%d_%H%M%S") + ".m4a")
    try:
        result = subprocess.run(
            ["termux-microphone-record", "-f", str(path), "-l", "0", "-e", "aac"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            bot.reply_to(message, "❌ تعذر بدء التسجيل.\n" + detail[:800])
            return

        RECORDING_FILE = path
        bot.reply_to(message, "🎙️ بدأ التسجيل الصوتي.\nأرسل /stop لإيقافه وإرسال الملف.")
    except Exception as e:
        RECORDING_FILE = None
        bot.reply_to(message, f"❌ خطأ في بدء التسجيل: {e}")

@bot.message_handler(commands=['stop'])
def stop_recording(message):
    global RECORDING_FILE
    if not is_admin(message):
        return
    if RECORDING_FILE is None:
        bot.reply_to(message, "ℹ️ لا يوجد تسجيل نشط.")
        return

    path = RECORDING_FILE
    result = None # تم تعريفها مسبقاً لتجنب خطأ UnboundLocalError
    try:
        result = subprocess.run(
            ["termux-microphone-record", "-q"],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            bot.reply_to(message, "❌ تعذر إيقاف التسجيل بأمان.\n" + detail[:800])
            return

        time.sleep(1)
        if not path.exists() or path.stat().st_size < 100:
            bot.reply_to(message, "❌ ملف التسجيل فارغ أو غير موجود.")
            return

        bot.reply_to(message, "📤 جارٍ إرسال التسجيل...")
        with open(path, "rb") as audio_file:
            bot.send_audio(message.chat.id, audio_file, title="تسجيل صوتي")
    except Exception as e:
        bot.reply_to(message, f"❌ حدث خطأ: {e}")
    finally:
        if result and result.returncode == 0:
            RECORDING_FILE = None
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass

# --- تشغيل البوت ---
if __name__ == "__main__":
    if not TOKEN or TOKEN == "ضع_التوكن_الجديد_هنا":
        raise SystemExit("ضع توكن البوت الجديد داخل TOKEN أولاً.")

    print("البوت يعمل الآن...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20, skip_pending=False)
        except requests.exceptions.ReadTimeout:
            print("انتهت مهلة الاتصال، ستتم إعادة المحاولة.")
            time.sleep(5)
        except requests.exceptions.RequestException as e:
            print(f"خطأ اتصال: {e}")
            time.sleep(10)
        except Exception as e:
            print(f"خطأ غير متوقع: {e}")
            time.sleep(5)
