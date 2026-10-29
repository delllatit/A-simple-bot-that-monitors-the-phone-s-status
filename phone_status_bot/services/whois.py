"""خدمة whois: استخراج الحقول الأساسية من مخرجات أمر whois."""

import re
import shutil
import subprocess

# استخراج الحقول الأساسية من مخرجات whois، مكافئ لـ:
#   whois <ip> | grep -iE "netname|descr|org-name|country"
WHOIS_FIELD_PATTERN = re.compile(
    r"^(?:\s*)(netname|descr|org-name|country)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)

# صيغة المعرّف المسموح تمريره للأمر (IP/نطاق/مضيف) — منع حقن الأوامر
TARGET_PATTERN = re.compile(r"[A-Za-z0-9._:-]+")

MAX_REPORT_LENGTH = 4000


def is_valid_target(arg):
    """التحقق الآمن من صيغة العنوان قبل تمريره لأمر whois."""
    return bool(TARGET_PATTERN.fullmatch(arg))


def extract_whois_fields(raw_output):
    """تصفية مخرجات whois إلى الحقول المطلوبة فقط مع إزالة التكرار."""
    results = []
    seen = set()
    for line in (raw_output or "").splitlines():
        match = WHOIS_FIELD_PATTERN.match(line)
        if not match:
            continue
        key = match.group(1).lower()
        value = match.group(2)
        entry = f"{key}: {value}"
        if entry.lower() not in seen:
            seen.add(entry.lower())
            results.append(entry)
    return results


def run_whois(target, timeout=30):
    """تنفيذ whois على عنوان موثوق الصيغة.

    يرفع FileNotFoundError إذا كان الأمر غير مثبت،
    و subprocess.TimeoutExpired عند تجاوز المهلة.
    يرجع tuple (fields, fallback_summary) حيث fallback يُستخدم عند غياب النتائج.
    """
    whois_bin = shutil.which("whois")
    if not whois_bin:
        raise FileNotFoundError("whois")

    result = subprocess.run(
        [whois_bin, target],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    fields = extract_whois_fields(result.stdout or "")
    fallback = (result.stderr.strip() or "No matching records found")[:300]
    return fields, fallback


def format_report(target, fields, is_public_ip=False):
    """بناء نص تقرير whois مع احترام حد طول رسائل Telegram."""
    header = f"🔎 نتائج whois للعنوان {target}"
    if is_public_ip:
        header += " (IP العام الحالي)"
    if not fields:
        return None
    body = "\n".join(fields)
    if len(body) > MAX_REPORT_LENGTH:
        body = body[:MAX_REPORT_LENGTH] + "\n... (تم اقتطاع النتائج)"
    return f"{header}\n\n{body}"
