"""خدمة whois: عرض مخرجات أمر whois كاملة ومقسّمة لتناسب Telegram."""

import re
import shutil
import subprocess

# صيغة المعرّف المسموح تمريره للأمر (IP/نطاق/مضيف) — منع حقن الأوامر
TARGET_PATTERN = re.compile(r"[A-Za-z0-9._:-]+")

# حد رسالة Telegram الرسمي 4096؛ نترك هامشاً بسيطاً للأمان
MAX_REPORT_LENGTH = 4000


def is_valid_target(arg):
    """التحقق الآمن من صيغة العنوان قبل تمريره لأمر whois."""
    return bool(TARGET_PATTERN.fullmatch(arg))


def clean_whois_output(raw):
    """إزالة أسطر التعليقات (%...) والأسطر الفارغة الزائدة، مع الإبقاء على كل بيانات whois."""
    lines = []
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if stripped.startswith("%"):
            continue
        lines.append(line.rstrip())

    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def run_whois(target, timeout=30):
    """تنفيذ whois على عنوان موثوق الصيغة وإرجاع (raw_output, stderr_summary).

    يرفع FileNotFoundError إذا كان الأمر غير مثبت،
    و subprocess.TimeoutExpired عند تجاوز المهلة.
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
    fallback = (result.stderr.strip() or "No matching records found")[:300]
    return result.stdout or "", fallback


def split_message(text, limit=MAX_REPORT_LENGTH):
    """تقسيم نص طويل إلى دفعات لا يتجاوز كل منها حد Telegram."""
    chunks = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) <= limit:
            current += line
            continue
        if current:
            chunks.append(current)
            current = ""
        # في حال كان سطر واحد أطول من الحد، نقسمه قسرياً
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current = line
    if current:
        chunks.append(current)
    return chunks


def format_report(target, raw_output, is_public_ip=False):
    """بناء تقرير whois كاملاً وإرجاعه كقائمة رسائل جاهزة للإرسال.

    يرجع None إذا لم توجد بيانات قابلة للعرض.
    """
    cleaned = clean_whois_output(raw_output)
    if not cleaned.strip():
        return None

    header = f"🔎 نتائج whois الكاملة للعنوان {target}"
    if is_public_ip:
        header += " (IP العام الحالي)"

    full_text = f"{header}\n\n{cleaned}"
    chunks = split_message(full_text, MAX_REPORT_LENGTH)

    # ترقيم الدفعات إذا كانت أكثر من رسالة واحدة
    if len(chunks) > 1:
        total = len(chunks)
        chunks = [f"({i}/{total})\n{chunk}" for i, chunk in enumerate(chunks, 1)]

    return chunks
