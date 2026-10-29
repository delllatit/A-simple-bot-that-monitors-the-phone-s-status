"""خدمة الشبكة: قراءات Wi-Fi والشبكة الخلوية وIP المحلي.

ملاحظة: تقارير البطارية موجودة في services/battery.py وقراءة IP العام في core/termux.py.
"""

import html
import os

from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.termux import run_termux_command, parse_json_output

CELL_INFO_COMMAND = ["termux-telephony-cellinfo"]
WIFI_COMMAND = ["termux-wifi-connectioninfo"]

# علامة خاصة ترجعها get_wifi_report عند عدم وجود اتصال نشط
NO_ACTIVE_WIFI = "__no_active_wifi__"

# تصنيف قوة الإشارة حسب dBm (مقياس RSRP لشبكات LTE/5G)
SIGNAL_BANDS = [
    (-80, "ممتازة 🟩"),
    (-90, "جيدة 🟩"),
    (-100, "متوسطة 🟨"),
    (-110, "ضعيفة 🟧"),
]
SIGNAL_UNKNOWN = "غير معروف"

# أنواع الشبكات بترتيب الأولوية في بيانات الخلية
NETWORK_TYPES = {
    "nr": "NR (5G)",
    "lte": "LTE (4G)",
    "tdscdma": "TD-SCDMA (3G)",
    "wcdma": "WCDMA (3G)",
    "gsm": "GSM (2G)",
    "cdma": "CDMA",
}

UNKNOWN_LABEL = "غير معروف"

SUB_KEYS = ("lte", "nr", "gsm", "cdma", "wcdma", "tdscdma")


def signal_quality_label(rssi_dbm):
    """تصنيف قوة الإشارة نصياً من قيمة dBm."""
    try:
        rssi = int(rssi_dbm)
    except (TypeError, ValueError):
        return SIGNAL_UNKNOWN
    for boundary, label in SIGNAL_BANDS:
        if rssi >= boundary:
            return label
    return "سيئة جداً 🟥"


def format_bytes(num_bytes):
    """تحويل عدد البايتات إلى صيغة مقروءة (B/KB/MB/GB/TB)."""
    try:
        value = float(num_bytes)
    except (TypeError, ValueError):
        return "غير متوفر"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def level_to_percent(level):
    """تقدير نسبة قوة الإشارة من مستوى Android (0-4) عند غياب dBm."""
    try:
        level = int(level)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, (level + 1) * 20))


def get_cellular_data_usage():
    """حجم بيانات الهاتف عبر إحصاءات /proc/uid_stat (يعمل بدون صلاحيات خاصة).

    يرجع dict فيه sent/received/total/by_uid أو None إن كانت الإحصاءات غير متاحة.
    """
    usage = {}
    try:
        for entry in os.listdir("/proc/uid_stat"):
            tcp_stat = os.path.join("/proc/uid_stat", entry, "tcp_snd")
            rx_stat = os.path.join("/proc/uid_stat", entry, "tcp_rcv")
            if not (os.path.isfile(tcp_stat) and os.path.isfile(rx_stat)):
                continue
            try:
                with open(tcp_stat) as f:
                    sent = int(f.read().strip() or 0)
                with open(rx_stat) as f:
                    received = int(f.read().strip() or 0)
            except (OSError, ValueError):
                continue
            uid = int(entry) if entry.isdigit() else entry
            stats = usage.get(uid, {"sent": 0, "received": 0})
            stats["sent"] += sent
            stats["received"] += received
            usage[uid] = stats
    except OSError:
        # /proc/uid_stat غير متاح على بعض الأجهزة/الأنظمة
        return None

    if not usage:
        return None

    total_sent = sum(s["sent"] for s in usage.values())
    total_received = sum(s["received"] for s in usage.values())
    return {
        "sent": total_sent,
        "received": total_received,
        "total": total_sent + total_received,
        "by_uid": usage,
    }


def _pick_best_cell(cells):
    """اختيار الخلية المسجلة الأحدث (الأعلى timestamp) لعرض تفاصيلها."""
    if not cells:
        return None
    try:
        return max(cells, key=lambda c: c.get("timestamp", 0) if isinstance(c, dict) else 0)
    except (TypeError, ValueError):
        last = cells[-1]
        return last if isinstance(last, dict) else None


def _detect_network_type(best_cell):
    """تحديد نوع الشبكة الحالية من مفاتيح بيانات الخلية."""
    for key, label in NETWORK_TYPES.items():
        if key in best_cell:
            if key == "nr":
                nr = best_cell.get("nr") or {}
                # tac != -1 يعني شبكة غير مستقلة (NSA) تعتمد على LTE
                return "NR (5G)" if nr.get("tac") == -1 else "NR (5G NSA)"
            return label
    return UNKNOWN_LABEL


def _extract_signal_metrics(best_cell):
    """استخراج dbm/rsrp/rsrq/sinr/asu من أول تقنية متاحة في الخلية."""
    dbm_value = rsrp = rsrq = sinr = asu = None
    for sub_key in SUB_KEYS:
        sub = best_cell.get(sub_key)
        if isinstance(sub, dict):
            dbm_value = sub.get("dbm")
            rsrp = sub.get("rsrp")
            rsrq = sub.get("rsrq")
            sinr = sub.get("sinr")
            asu = sub.get("asu")
            break
    if dbm_value is None:
        dbm_value = best_cell.get("dbm")
    return dbm_value, rsrp, rsrq, sinr, asu


def build_signal_lines(best_cell):
    """بناء أسطر قسم الإشارة (HTML) من بيانات الخلية المختارة."""
    if not isinstance(best_cell, dict):
        return f"- <b>نوع الشبكة:</b> {SIGNAL_UNKNOWN}\n- <b>قوة الإشارة:</b> {SIGNAL_UNKNOWN}\n"

    network_type = _detect_network_type(best_cell)
    dbm_value, rsrp, rsrq, sinr, asu = _extract_signal_metrics(best_cell)

    quality = signal_quality_label(dbm_value)
    if quality == SIGNAL_UNKNOWN and best_cell.get("level") is not None:
        percent = level_to_percent(best_cell.get("level"))
        if percent is not None:
            quality = f"تقديرية ({percent}% من مستوى Android)"

    lines = f"- <b>نوع الشبكة:</b> {html.escape(network_type)}\n"
    if dbm_value is not None:
        lines += f"- <b>قوة الإشارة:</b> {html.escape(str(dbm_value))} dBm — {quality}\n"
    else:
        lines += f"- <b>قوة الإشارة:</b> {quality}\n"
    for label, value in (("RSRP", rsrp), ("RSRQ", rsrq), ("SINR", sinr), ("ASU", asu)):
        if value is not None:
            unit = "" if label == "ASU" else (" dBm" if label == "RSRP" else " dB")
            lines += f"- <b>{label}:</b> {html.escape(str(value))}{unit}\n"
    return lines


def build_data_section(usage):
    """قسم بيانات الهاتف (HTML) من إحصاءات الاستخدام أو رسالة تعذر."""
    if usage:
        return (
            "\n📊 <b>بيانات الهاتف (منذ آخر تصفير للنظام):</b>\n"
            f"- <b>إجمالي الاستخدام:</b> {format_bytes(usage['total'])}\n"
            f"- <b>رفع (Sent):</b> {format_bytes(usage['sent'])}\n"
            f"- <b>تنزيل (Received):</b> {format_bytes(usage['received'])}\n"
            "- <b>ملاحظة:</b> الإحصاءات تشمل حركة مرور التطبيقات عبر الشبكة الخلوية."
        )
    return (
        "\n📊 <b>بيانات الهاتف:</b>\n"
        "- تعذر قراءة إحصاءات البيانات من النظام.\n"
        "- جرّب استخدام أداة مثل TrafficStats أو راقب الاستهلاك من إعدادات الجهاز."
    )


def get_local_ip(timeout=10):
    """قراءة IP المحلي من مخرجات termux-wifi-connectioninfo؛ يرجع 'غير متاح' عند التعذر."""
    output = run_termux_command(WIFI_COMMAND, timeout=timeout)
    data = parse_json_output(output)
    if isinstance(data, dict):
        return data.get("ip", "غير متاح")
    return "غير متاح"


def get_wifi_report():
    """تقرير Wi-Fi بصيغة HTML، أو None عند تعذر القراءة، أو NO_ACTIVE_WIFI عند عدم الاتصال."""
    output = run_termux_command(WIFI_COMMAND)
    data = parse_json_output(output)
    if not isinstance(data, dict):
        logger.warning("تعذر قراءة شبكة: %s", output)
        return None
    if data.get("supplicant_state") != "COMPLETED":
        return NO_ACTIVE_WIFI
    return (
        "📶 <b>معلومات شبكة Wi-Fi:</b>\n"
        f"- <b>اسم الشبكة:</b> {html.escape(str(data.get('ssid', 'N/A')))}\n"
        f"- <b>عنوان IP:</b> {html.escape(str(data.get('ip', 'N/A')))}\n"
        f"- <b>BSSID:</b> {html.escape(str(data.get('bssid', 'N/A')))}\n"
        f"- <b>سرعة الاتصال:</b> {html.escape(str(data.get('link_speed_mbps', 'N/A')))} Mbps\n"
        f"- <b>قوة الإشارة:</b> {html.escape(str(data.get('rssi', 'N/A')))} dBm"
    )


def get_cellular_report():
    """إرجاع تقرير HTML كامل للشبكة الخلوية، أو None عند تعذر القراءة."""
    output = run_termux_command(CELL_INFO_COMMAND)
    data = parse_json_output(output)
    if not isinstance(data, dict):
        logger.warning("تعذر قراءة المعلومات الخلوية: %s", output)
        return None

    cell = data.get("cellInformation") or {}
    if not isinstance(cell, dict):
        cell = {}

    all_cells = cell.get("allCellInfo") or []
    registered_cells = cell.get("registeredCellInfo") or []
    source_cells = registered_cells or all_cells

    best_cell = _pick_best_cell(source_cells)
    signal_lines = build_signal_lines(best_cell)

    display_cells = len(all_cells) if isinstance(all_cells, list) else 0
    signal_lines += f"- <b>عدد الخلايا المرئية:</b> {display_cells}\n"

    # معلومات المشغل من TelephonyManager
    tm = data.get("telephonyManagerInformation") or {}
    if not isinstance(tm, dict):
        tm = {}
    operator = tm.get("networkOperatorName") or tm.get("simOperatorName") or "غير متوفر"
    mcc_mnc = tm.get("networkOperator") or "غير متوفر"
    service_state = "متصل بالخدمة" if tm.get("serviceState") == 5 else str(
        tm.get("serviceState", "غير معروف")
    )

    usage = get_cellular_data_usage()

    return (
        "📡 <b>معلومات الشبكة الخلوية:</b>\n"
        f"{signal_lines}"
        f"- <b>المشغل:</b> {html.escape(str(operator))} ({html.escape(str(mcc_mnc))})\n"
        f"- <b>حالة الخدمة:</b> {html.escape(service_state)}\n"
        f"{build_data_section(usage)}"
    )
