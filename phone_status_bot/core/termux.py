"""أدوات تنفيذ أوامر Termux:API وتحليل مخرجاتها، بالإضافة إلى طلبات HTTP."""

import json
import re
import subprocess

import requests

from phone_status_bot.core import config

IPIFY_URL = "https://api.ipify.org"

# نمط يميّز مخرجات الأخطاء (نص عربي أو كلمة error الإنجليزية) عن البيانات الحقيقية
_ERROR_OUTPUT_RE = re.compile(r"^خطأ|^error\b", re.IGNORECASE)


def _is_error_output(output):
    """هل هذه المخرجات رسالة خطأ وليست بيانات JSON صالحة؟"""
    if not output:
        return True
    stripped = output.strip()
    # بيانات حقيقية تبدأ عادةً بـ { أو [ — لا تُعامل كخطأ حتى لو احتوت كلمة error
    if stripped[:1] in ("{", "["):
        return False
    return bool(_ERROR_OUTPUT_RE.match(stripped))


def run_termux_command(command, timeout=30):
    """تنفيذ أمر Termux وإرجاع المخرجات النصية، أو رسالة خطأ عربية عند الفشل."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
        stdout = result.stdout.strip()
        # بعض أدوات Termux:API تكتب الخطأ في stdout وتخرج بكود 0 — نفحصها هنا
        if not stdout or _is_error_output(stdout):
            stderr = (result.stderr or "").strip()
            if stderr:
                return f"خطأ في تنفيذ الأمر: {stderr}"
            if not stdout:
                return "خطأ: الأمر لم يُرجع أي مخرجات."
        return stdout
    except subprocess.TimeoutExpired:
        return f"خطأ: انتهت مهلة تنفيذ الأمر بعد {timeout} ثانية."
    except subprocess.CalledProcessError as e:
        error = e.stderr.strip() if e.stderr else str(e)
        return f"خطأ في تنفيذ الأمر: {error}"
    except FileNotFoundError:
        return "خطأ: الأمر غير موجود. تأكد من تثبيت Termux:API."
    except OSError as e:
        return f"خطأ في النظام: {e}"


def parse_json_output(output):
    """تحويل مخرجات الأوامر إلى dict/list؛ يرجع None عند التعذر.

    يرفض رسائل الخطأ العربية/الإنجليزية التي ترجعها run_termux_command،
    وكذلك المصفوفات الفارغة [] (تعني عادةً أن الخدمة لم تُرجع بيانات صالحة،
    مثلما يظهر في سجلات termux-telephony-cellinfo على بعض الأجهزة).
    """
    if _is_error_output(output):
        return None
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None
    # مصفوفة فارغة = لا بيانات خلوية فعلية → تعامل كتعذر قراءة لا كتقرير صالح
    if isinstance(data, list) and not data:
        return None
    return data


def fetch_public_ip(timeout=10):
    """جلب IP العام للجهاز عبر api.ipify.org.

    يرفع requests.RequestException عند فشل الشبكة.
    """
    resp = requests.get(IPIFY_URL, timeout=timeout)
    resp.raise_for_status()
    return resp.text.strip()


def resolve_termux_bin(name):
    """تحديد مسار أمر Termux بدقة (لتفادي مشاكل PATH/tmux)، مع خيار أخير للاسم المجرد."""
    from pathlib import Path

    cmd_path = Path(config.TERMUX_PREFIX) / "bin" / name
    return str(cmd_path) if cmd_path.exists() else name
