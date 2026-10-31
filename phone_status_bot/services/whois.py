"""خدمة whois: عرض مخرجات whois كاملة مع ملخص وقسم تفاصيل، ومقسّمة لتناسب Telegram."""

import html
import re
import shutil
import subprocess

TARGET_PATTERN = re.compile(r"[A-Za-z0-9._:-]+")
MAX_REPORT_LENGTH = 4000
PRE_OVERHEAD = len("<pre></pre>")   # 11 حرفاً
SAFETY_MARGIN = 200                 # هامش للترقيم ولأي إضافات

# الحقول المفتاحية التي تُعرض في الملخص
SUMMARY_FIELDS = [
    ("inetnum", r"^inetnum:\s*(.+)$",         "النطاق"),
    ("netname", r"^netname:\s*(.+)$",         "اسم الشبكة"),
    ("descr",   r"^descr:\s*(.+)$",           "الوصف"),
    ("country", r"^country:\s*(.+)$",         "الدولة"),
    ("origin",  r"^origin:\s*(.+)$",          "ASN"),
    ("route",   r"^route:\s*(.+)$",           "المسار"),
    ("org",     r"^(?:org-name|org):\s*(.+)$","الجهة"),
]

ABUSE_PATTERN   = re.compile(r"^%\s*Abuse contact\b.*?\bis\s+'([^']+)'", re.IGNORECASE)
SECTION_PATTERN = re.compile(r"^%\s*Information related to\s+(.+)$",    re.IGNORECASE)

# خريطة رموز دول شائعة → علم
COUNTRY_FLAGS = {
    "SY": "🇸🇾", "SA": "🇸🇦", "AE": "🇦🇪", "EG": "🇪🇬", "JO": "🇯🇴",
    "IQ": "🇮🇶", "LB": "🇱🇧", "PS": "🇵🇸", "KW": "🇰🇼", "QA": "🇶🇦",
    "US": "🇺🇸", "GB": "🇬🇧", "DE": "🇩🇪", "FR": "🇫🇷", "TR": "🇹🇷",
    "RU": "🇷🇺", "CN": "🇨🇳", "NL": "🇳🇱", "CA": "🇨🇦", "AU": "🇦🇺",
}


def is_valid_target(arg):
    """التحقق الآمن من صيغة العنوان قبل تمريره لأمر whois."""
    return bool(TARGET_PATTERN.fullmatch(arg))


def run_whois(target, timeout=30):
    """تنفيذ whois على عنوان موثوق الصيغة وإرجاع (raw_output, stderr_summary)."""
    whois_bin = shutil.which("whois")
    if not whois_bin:
        raise FileNotFoundError("whois")

    result = subprocess.run(
        [whois_bin, target], capture_output=True, text=True, timeout=timeout,
    )
    fallback = (result.stderr.strip() or "No matching records found")[:300]
    return result.stdout or "", fallback


def _clean_whois_lines(raw):
    """حذف أسطر التعليقات % وتحويل فواصل الأقسام إلى عناوين مرئية."""
    lines = []
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if stripped.startswith("%"):
            m = SECTION_PATTERN.match(stripped)
            if m:
                label = re.sub(
                    r"^Information related to\s*", "",
                    m.group(1), flags=re.IGNORECASE,
                ).strip()
                lines.append("")
                lines.append(f"─── {label} ───")
                lines.append("")
            continue
        lines.append(line.rstrip())
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def _extract_summary(raw):
    """استخراج أهم الحقول من المخرجات الخام لبناء بطاقة الملخص."""
    summary = {}
    for line in (raw or "").splitlines():
        for key, pattern, _ in SUMMARY_FIELDS:
            if key in summary:
                continue
            m = re.match(pattern, line, re.IGNORECASE)
            if m:
                summary[key] = m.group(1).strip()
        if "abuse" not in summary:
            m = ABUSE_PATTERN.match(line)
            if m:
                summary["abuse"] = m.group(1).strip()
    return summary


def _build_summary_block(summary):
    """بناء بطاقة الملخص بصيغة HTML، أو نص فارغ إذا لم تتوفر حقول."""
    if not summary:
        return ""
    lines = ["📋 <b>الملخص</b>"]
    for key, _pat, label in SUMMARY_FIELDS:
        if key in summary:
            val = summary[key]
            if key == "country":
                flag = COUNTRY_FLAGS.get(val.upper())
                if flag:
                    val = f"{val} {flag}"
            lines.append(f"• <b>{label}:</b> <code>{html.escape(val, quote=False)}</code>")
    if "abuse" in summary:
        lines.append(
            f"• <b>Abuse:</b> <code>{html.escape(summary['abuse'], quote=False)}</code>"
        )
    return "\n".join(lines)


def format_report(target, raw_output, is_public_ip=False):
    """بناء قائمة رسائل HTML جاهزة للإرسال (كل عنصر <= MAX_REPORT_LENGTH)."""
    if not raw_output or not raw_output.strip():
        return None

    # 1) الترويسة
    header = f"🔎 <b>whois</b> — <code>{html.escape(target, quote=False)}</code>"
    if is_public_ip:
        header += " <i>(IP العام)</i>"

    # 2) بطاقة الملخص
    summary_block = _build_summary_block(_extract_summary(raw_output))
    head_parts = [header]
    if summary_block:
        head_parts.append(summary_block)
    head_block = "\n\n".join(head_parts) + "\n\n"

    # 3) التفاصيل (خام بعد التنظيف + تهريب HTML سطراً سطراً)
    raw_lines = _clean_whois_lines(raw_output)
    escaped_lines = [html.escape(l, quote=False) for l in raw_lines]
    details_text = "\n".join(escaped_lines)

    budget = MAX_REPORT_LENGTH - SAFETY_MARGIN

    # 4) كل شيء في رسالة واحدة؟
    if len(head_block) + len(details_text) + PRE_OVERHEAD <= budget:
        return [f"{head_block}<pre>{details_text}</pre>"]

    # 5) وإلا: نقسم التفاصيل سطراً سطراً (الأسطر آمنة بعد التهريب)
    chunks = []
    current = []
    current_len = 0
    first_limit = max(budget - len(head_block) - PRE_OVERHEAD, 500)
    limit = first_limit
    is_first = True

    for line in escaped_lines:
        line_len = len(line) + 1  # +1 للـ newline
        if current and current_len + line_len > limit:
            body = "\n".join(current)
            wrapped = f"<pre>{body}</pre>"
            chunks.append(head_block + wrapped if is_first else wrapped)
            is_first = False
            current = []
            current_len = 0
            limit = budget - PRE_OVERHEAD
        current.append(line)
        current_len += line_len

    if current:
        body = "\n".join(current)
        wrapped = f"<pre>{body}</pre>"
        chunks.append(head_block + wrapped if is_first else wrapped)

    # 6) ترقيم عند التعدد
    if len(chunks) > 1:
        total = len(chunks)
        chunks = [f"<i>({i}/{total})</i>\n{c}" for i, c in enumerate(chunks, 1)]

    return chunks
