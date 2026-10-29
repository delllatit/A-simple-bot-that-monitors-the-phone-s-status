"""خدمة التسجيل الصوتي: بدء/إيقاف/تنظيف + مراقب الإيقاف التلقائي.

كل العمليات آمنة الخيوط عبر state.RECORDING_LOCK، والتنظيف idempotent
ليُستدعى من /stop ومن الإيقاف التلقائي ومن atexit/الإشارات دون تكرار الأثر.
"""

import subprocess
import time

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import safe_send

MIN_VALID_FILE_SIZE = 100  # بايت — أقل حجم مقبول لملف تسجيل صالح


def _stop_recorder(timeout=20):
    """إيقاف مسجل Termux؛ يرجع True عند النجاح."""
    try:
        result = subprocess.run(
            ["termux-microphone-record", "-q"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning("تعذر إيقاف المسجل: %s", e)
        return False


def cleanup_recording():
    """يوقف أي تسجيل نشط ويحذف الملف الحساس (آمن الاستدعاء المتكرر)."""
    path = state.take_recording_file()
    if path is None:
        return
    _stop_recorder(timeout=10)
    _delete_file(path)


def cleanup_orphan_recordings():
    """يوقف أي تسجيل شغّال من جلسة سابقة ويحذف ملفات تسجيل يتيمة أقدم من ساعة."""
    _stop_recorder(timeout=10)
    cutoff = time.time() - 3600
    for f in config.RECORDING_DIR.glob("recording_*.m4a"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                logger.info("حذف ملف تسجيل يتيم: %s", f)
        except OSError:
            pass


def start_recording():
    """بدء تسجيل جديد.

    يرجع (True, None) عند النجاح أو (False، سبب_للسجل) عند الفشل.
    """
    with state.RECORDING_LOCK:
        if state.RECORDING_FILE is not None:
            return False, "already_active"

        file_path = config.RECORDING_DIR / (
            "recording_" + time.strftime("%Y%m%d_%H%M%S") + ".m4a"
        )

        try:
            result = subprocess.run(
                # مدة قصوى للتسجيل بدل -l 0 غير المحدود
                ["termux-microphone-record", "-f", str(file_path),
                 "-l", str(config.RECORD_MAX_SECONDS), "-e", "aac"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                return False, f"record_failed: {detail}"

            state.RECORDING_FILE = file_path
            return True, None
        except Exception as e:
            state.RECORDING_FILE = None
            return False, f"exception: {e}"


def stop_recording():
    """إيقاف التسجيل النشط.

    يرجع أحد القيم:
      - ("no_recording", None)     : لا يوجد تسجيل نشط
      - ("stop_failed", None)      : تعذر إيقاف المسجل
      - ("empty_file", path)       : الملف فارغ أو غير موجود
      - ("ok", path)               : نجاح — المستدعي يرسل الملف ثم يحذفه
    """
    path = state.take_recording_file()
    if path is None:
        return "no_recording", None

    if not _stop_recorder():
        return "stop_failed", path

    time.sleep(1)  # انتظار تفريغ المخزن المؤقت إلى القرص
    if not path.exists() or path.stat().st_size < MIN_VALID_FILE_SIZE:
        _delete_file(path)
        return "empty_file", path

    return "ok", path


def finish_and_delete(path):
    """حذف ملف التسجيل بعد إرساله (تستخدمها معالجات /stop)."""
    _delete_file(path)


def auto_stop_watcher():
    """مراقب يعمل في خيط منفصل: إيقاف تلقائي بعد RECORD_MAX_SECONDS إن لم يُستدعَ /stop."""
    deadline = time.monotonic() + config.RECORD_MAX_SECONDS
    while time.monotonic() < deadline and not state.SHUTDOWN.is_set():
        time.sleep(1)
        if state.get_recording_file() is None:
            return  # تم إيقاف التسجيل يدوياً عبر /stop

    if state.SHUTDOWN.is_set():
        return

    path = state.take_recording_file()
    if path is None:
        return

    logger.warning(
        "تم إيقاف التسجيل تلقائياً بعد تجاوز الحد الأقصى (%d ثانية)",
        config.RECORD_MAX_SECONDS,
    )
    try:
        _stop_recorder()
        time.sleep(1)
        for admin_id in config.ADMIN_IDS:
            if path.exists() and path.stat().st_size >= MIN_VALID_FILE_SIZE:
                with open(path, "rb") as audio_file:
                    state.bot.send_audio(admin_id, audio_file, title="تسجيل صوتي (إيقاف تلقائي)")
            else:
                safe_send(admin_id, "⏹️ تم إيقاف التسجيل تلقائياً بعد تجاوز الحد الأقصى المسموح.")
    except Exception as e:
        logger.exception("فشل الإيقاف التلقائي/إرسال التسجيل: %s", e)
    finally:
        _delete_file(path)


def _delete_file(path):
    """حذف ملف بأمان وتسجيل أي فشل."""
    try:
        if path.exists():
            path.unlink()
            logger.info("تم حذف ملف التسجيل المعلق: %s", path)
    except OSError as e:
        logger.warning("فشل حذف ملف التسجيل: %s", e)
