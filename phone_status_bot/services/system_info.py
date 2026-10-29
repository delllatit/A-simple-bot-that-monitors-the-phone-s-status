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

def read_loadavg():
    """قراءة متوسط الحمل (1/5/15 دقيقة) من /proc/loadavg."""
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        return parts[0], parts[1], parts[2]
    except (OSError, IndexError):
        return "N/A", "N/A", "N/A"


def read_cpu_percent(interval=CPU_SAMPLE_INTERVAL):
    """نسبة استخدام المعالج من فرق قراءتين في /proc/stat، أو None عند التعذر."""
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


def read_meminfo():
    """قراءة MemTotal/MemAvailable/SwapTotal/SwapFree بالكيلوبايت من /proc/meminfo."""
    keys = {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}
    values = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, val = line.partition(":")
                if key in keys:
                    num = val.strip().split(" ")[0]
                    if num.isdigit():
                        values[key] = int(num)
    except OSError:
        pass
    return values


def count_processes():
    """عدد العمليات الجارية من /proc، أو None عند التعذر."""
    try:
        return sum(1 for p in Path("/proc").iterdir() if p.name.isdigit())
    except OSError:
        return None


def get_cpu_report():
    """تقرير HTML لحالة المعالج والذاكرة وعدد العمليات."""
    load1, load5, load15 = read_loadavg()
    cpu_count = os.cpu_count() or 1
    cpu_percent = read_cpu_percent()
    mem = read_meminfo()

    lines = ["🖥️ <b>حالة المعالج والذاكرة:</b>", ""]

    cpu_line = f"- <b>الحمل (1/5/15 دقيقة):</b> {load1} / {load5} / {load15} ({cpu_count} نواة)"
    if cpu_percent is not None:
        cpu_line += f"\n- <b>استخدام المعالج:</b> {cpu_percent:.1f}%"
    lines.append(cpu_line)

    mem_total_kb = mem.get("MemTotal")
    mem_avail_kb = mem.get("MemAvailable")
    if mem_total_kb and mem_avail_kb is not None:
        used_mb = (mem_total_kb - mem_avail_kb) / 1024
        total_mb = mem_total_kb / 1024
        pct = (used_mb / total_mb * 100) if total_mb else 0
        lines.append(f"- <b>الذاكرة المستخدمة:</b> {used_mb:.0f} MB من {total_mb:.0f} MB ({pct:.1f}%)")
    else:
        lines.append("- <b>الذاكرة:</b> غير متاحة")

    swap_total_kb = mem.get("SwapTotal")
    if swap_total_kb:
        swap_used_mb = (swap_total_kb - (mem.get("SwapFree") or 0)) / 1024
        lines.append(f"- <b>Swap:</b> {swap_used_mb:.0f} MB من {swap_total_kb / 1024:.0f} MB")

    proc_count = count_processes()
    if proc_count is not None:
        lines.append(f"- <b>عدد العمليات:</b> {proc_count}")

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
        # الناتج الخام يُسجَّل في اللوج فقط — لا يُعرض للمستخدم
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
