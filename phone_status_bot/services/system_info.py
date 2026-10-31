"""خدمة النظام المحلي: مساحة القرص، المعالج والذاكرة، وجهات الاتصال."""

import html
import json
import os
import shutil as _shutil
import subprocess
import time
from pathlib import Path

from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.termux import resolve_termux_bin

MAX_CONTACTS = 100          # حد أقصى لعرض جهات الاتصال في رسالة واحدة
MAX_MESSAGE_LENGTH = 4000   # حد طول رسائل Telegram
CPU_SAMPLE_INTERVAL = 0.5   # فرق القراءتين لحساب نسبة استخدام المعالج


# ==================== التخزين ====================

def get_storage_report():
    """تقرير HTML لمساحة القرص باستخدام shutil.disk_usage (لا تحتاج أمر df)."""
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
            usage = _shutil.disk_usage(target)
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
        return None
    return "💾 <b>مساحة القرص:</b>\n\n" + "\n\n".join(rows)


# ==================== المعالج والذاكرة ====================

def read_cpu_percent(interval=CPU_SAMPLE_INTERVAL):
    """نسبة استخدام المعالج اللحظية من فرق قراءتين في /proc/stat، أو None."""
    def read_times():
        with open("/proc/stat") as f:
            fields = f.readline().split()[1:]
        values = [int(x) for x in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle

    try:
        t1, i1 = read_times()
        time.sleep(interval)
        t2, i2 = read_times()
        dt = t2 - t1
        if dt > 0:
            return (1 - (i2 - i1) / dt) * 100
    except (OSError, IndexError, ValueError):
        pass
    return None


def _progress_bar(percent, width=10):
    """شريط تقدم نصي بمحاذاة ثابتة."""
    percent = max(0, min(100, percent))
    filled = round(percent / 100 * width)
    return "▓" * filled + "░" * (width - filled)


def _quality_icon(percent):
    """أيقونة لونية حسب نسبة الاستهلاك."""
    if percent < 50:
        return "🟩"
    if percent < 75:
        return "🟨"
    if percent < 90:
        return "🟧"
    return "🟥"


def _format_mb(kb):
    """تحويل KB إلى MB بصيغة مقروءة."""
    return f"{kb / 1024:.0f} MB"


def _read_loadavg():
    """قراءة متوسط الحمل من /proc/loadavg مع fallback إلى os.getloadavg()."""
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        return float(parts[0]), float(parts[1]), float(parts[2])
    except (OSError, ValueError, IndexError):
        pass
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        return None, None, None


def _read_cpu_cores():
    """عدد أنوية المعالج من /proc/cpuinfo، مع fallback إلى os.cpu_count()."""
    try:
        with open("/proc/cpuinfo") as f:
            return sum(1 for line in f if line.startswith("processor"))
    except OSError:
        return os.cpu_count() or 1


def _read_meminfo():
    """قراءة قيم /proc/meminfo إلى dict (كيلوبايت)."""
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, val = line.partition(":")
                parts = val.strip().split()
                if parts and parts[0].isdigit():
                    info[key.strip()] = int(parts[0])
    except OSError:
        return None
    return info or None


def _count_processes():
    """عدد العمليات النشطة (مدخلات رقمية في /proc)."""
    try:
        return sum(1 for e in os.listdir("/proc") if e.isdigit())
    except OSError:
        return None


def get_cpu_report():
    """تقرير HTML عن حالة المعالج والذاكرة — بتنسيق أوضح مع أشرطة ومؤشرات لونية."""
    lines = ["🖥️ <b>حالة المعالج والذاكرة</b>"]

    # ---------- المعالج ----------
    cores = _read_cpu_cores()
    load1, load5, load15 = _read_loadavg()

    lines.append("")
    lines.append(f"⚙️ <b>المعالج</b> ({cores} {'أنوية' if cores != 1 else 'نواة'})")

    # نسبة الاستخدام اللحظية (فرق قراءتين في /proc/stat)
    cpu_pct = read_cpu_percent()
    if cpu_pct is not None:
        bar = _progress_bar(cpu_pct)
        icon = _quality_icon(cpu_pct)
        lines.append(
            f"• الاستخدام الآن: <code>{bar}</code> "
            f"<b>{cpu_pct:.0f}%</b> {icon}"
        )
    else:
        lines.append("• الاستخدام الآن: <i>غير متاح</i>")

    # متوسط الحمل (loadavg)
    if load1 is not None:
        load_pct = min(100.0, load1 / cores * 100)
        bar = _progress_bar(load_pct)
        icon = _quality_icon(load_pct)
        lines.append(
            f"• الحمل: <code>{load1:.2f}</code> → "
            f"<code>{bar}</code> <b>{load_pct:.0f}%</b> {icon}"
        )
        lines.append(
            f"• المتوسط (1/5/15): "
            f"<code>{load1:.2f}</code> / <code>{load5:.2f}</code> / <code>{load15:.2f}</code>"
        )
    else:
        lines.append("• الحمل: <i>غير متاح</i>")

    # ---------- الذاكرة ----------
    meminfo = _read_meminfo()
    lines.append("")

    if meminfo and meminfo.get("MemTotal"):
        total_kb = meminfo["MemTotal"]
        avail_kb = meminfo.get("MemAvailable") or meminfo.get("MemFree", 0)
        used_kb = total_kb - avail_kb

        used_pct = used_kb / total_kb * 100
        bar = _progress_bar(used_pct)
        icon = _quality_icon(used_pct)

        lines.append("💾 <b>الذاكرة RAM</b>")
        lines.append(f"• <code>{bar}</code> <b>{used_pct:.1f}%</b> {icon}")
        lines.append(
            f"• المستخدمة: <code>{_format_mb(used_kb)}</code> "
            f"من <code>{_format_mb(total_kb)}</code>"
        )
        lines.append(f"• الحرة: <code>{_format_mb(avail_kb)}</code>")
    else:
        lines.append("💾 <b>الذاكرة RAM</b>")
        lines.append("• <i>غير متاح</i>")

    # ---------- Swap ----------
    if meminfo:
        swap_total = meminfo.get("SwapTotal", 0)
        swap_free = meminfo.get("SwapFree", 0)
        if swap_total > 0:
            swap_used = swap_total - swap_free
            swap_pct = swap_used / swap_total * 100
            bar = _progress_bar(swap_pct)
            icon = _quality_icon(swap_pct)

            lines.append("")
            lines.append("🔄 <b>Swap</b>")
            lines.append(f"• <code>{bar}</code> <b>{swap_pct:.1f}%</b> {icon}")
            lines.append(
                f"• المستخدم: <code>{_format_mb(swap_used)}</code> "
                f"من <code>{_format_mb(swap_total)}</code>"
            )

    # ---------- العمليات ----------
    procs = _count_processes()
    if procs is not None:
        lines.append("")
        lines.append(f"🔢 <b>العمليات النشطة:</b> <code>{procs}</code>")

    return "\n".join(lines)


# ==================== جهات الاتصال ====================

def fetch_contacts():
    """قراءة جهات الاتصال عبر termux-contact-list.

    يرجع list من dicts.
    يرفع exceptions واضحة الأنواع ليترجمها المعالج إلى رسائل مناسبة:
      - RuntimeError(detail) : فشل الأمر أو ناتج فارغ أو صيغة غير متوقعة
      - FileNotFoundError    : الأمر غير مثبت
    """
    cmd = resolve_termux_bin("termux-contact-list")
    result = subprocess.run([cmd], capture_output=True, text=True, timeout=30)

    if result.returncode != 0:
        raise RuntimeError(f"exit={result.returncode}: {(result.stderr or result.stdout).strip()}")
    if not result.stdout.strip():
        raise RuntimeError("empty_output")

    try:
        contacts = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.warning("JSON غير صالح من termux-contact-list: %s", result.stdout[:800])
        raise RuntimeError("invalid_json")

    if not isinstance(contacts, list):
        raise RuntimeError("unexpected_format")
    return contacts


def format_contacts_report(contacts):
    """تنسيق قائمة جهات الاتصال كـ HTML مع الحد الأقصى وحذف الزائد."""
    if not contacts:
        return "📇 لا توجد جهات اتصال."

    shown = contacts[:MAX_CONTACTS]
    lines = []
    for c in shown:
        if not isinstance(c, dict):
            continue
        name = c.get("name", "بدون اسم")
        number = c.get("number", "بدون رقم")
        lines.append(f"• <b>{html.escape(str(name))}</b>: <code>{html.escape(str(number))}</code>")

    header = f"📇 <b>جهات الاتصال ({len(contacts)}):</b>"
    if len(contacts) > MAX_CONTACTS:
        header += f"\n(يتم عرض أول {MAX_CONTACTS} فقط)"

    report = header + "\n\n" + "\n".join(lines)
    if len(report) > MAX_MESSAGE_LENGTH:
        report = report[:3900] + "\n..."
    return report
