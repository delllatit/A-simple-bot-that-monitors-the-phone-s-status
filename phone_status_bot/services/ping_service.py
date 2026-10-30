"""خدمة فحص اتصال الإنترنت: ICMP + TCP + DNS."""

import platform
import socket
import subprocess
import time


def check_icmp(host="8.8.8.8", count=4, timeout=5):
    """يشغّل ping ويعيد (نجاح؟، الناتج، الخطأ)."""
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), host]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=count * timeout + 5,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", f"انتهت المهلة بعد {count * timeout} ثانية"
    except FileNotFoundError:
        return False, "", "أمر ping غير متوفر"
    except Exception as e:
        return False, "", str(e)


def check_tcp(host="1.1.1.1", port=53, timeout=3):
    """فحص اتصال TCP — يعمل حتى لو كان ICMP محجوباً."""
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return True, (time.monotonic() - start) * 1000
    except OSError:
        return False, None


def check_dns(host="google.com"):
    """تحقق من تحليل DNS."""
    start = time.monotonic()
    try:
        socket.gethostbyname(host)
        return True, (time.monotonic() - start) * 1000
    except OSError:
        return False, None
