"""خدمة الرسائل والمكالمات: إرسال SMS وبدء مكالمة عبر Termux:API."""

import re
import subprocess

SMS_COMMAND = "termux-sms-send"
CALL_COMMAND = "termux-telephony-call"

# الصيغة الدولية المقبولة لأرقام الهاتف
PHONE_PATTERN = re.compile(r"\+?\d{7,15}")


def normalize_phone(raw):
    """إزالة المسافات من رقم هاتف."""
    return re.sub(r"\s+", "", raw)


def is_valid_phone(phone):
    """التحقق من صلاحية رقم الهاتف (الصيغة الدولية)."""
    return bool(PHONE_PATTERN.fullmatch(phone))


def _run(command_args, timeout=20):
    """تنفيذ أمر موثوق الصيغة؛ يرفع CalledProcessError/FileNotFoundError عند الفشل."""
    return subprocess.run(
        command_args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def send_sms(phone_number, sms_text):
    """إرسال رسالة SMS.

    يرجع tuple (success, detail) حيث detail للسجل فقط ولا يُعرض للمستخدم.
    """
    if not is_valid_phone(phone_number) or not sms_text:
        return False, "invalid_input"
    try:
        result = _run([SMS_COMMAND, "-n", phone_number, sms_text])
        if result.returncode != 0:
            return False, (result.stderr or result.stdout).strip()
        return True, None
    except FileNotFoundError:
        return False, f"{SMS_COMMAND} غير موجود"


def make_call(phone_number):
    """بدء مكالمة. يرجع tuple (success, detail) بنفس conventions send_sms."""
    if not is_valid_phone(phone_number):
        return False, "invalid_input"
    try:
        result = _run([CALL_COMMAND, phone_number])
        if result.returncode != 0:
            return False, (result.stderr or result.stdout).strip()
        return True, None
    except FileNotFoundError:
        return False, f"{CALL_COMMAND} غير موجود"
