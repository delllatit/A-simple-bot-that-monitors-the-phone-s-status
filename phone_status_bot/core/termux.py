"""أدوات تنفيذ أوامر Termux:API وتحليل مخرجاتها، بالإضافة إلى طلبات HTTP."""

import json
import subprocess

import requests

from phone_status_bot.core import config

IPIFY_URL = "https://api.ipify.org"


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
        return result.stdout.strip()
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
    """تحويل مخرجات الأوامر إلى dict/list؛ يرجع None عند التعذر."""
    if not output or output.startswith("خطأ:"):
        return None
    try:
        return json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return None


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
