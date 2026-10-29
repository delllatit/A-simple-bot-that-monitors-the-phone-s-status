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
    """اختيار أفضل خلية لعرض تفاصيلها.

    القاعدة (بالأولوية): الخلية المسجّلة ذات القراءة الصالحة الأعلى dBm؛
    فإن لم توجد قراءات صالحة، أي خلية مسجّلة؛ ثم الخلية الأحدث timestamp؛
    وأخيراً العنصر الأخير. تُتجاهل القيم الشاذة مثل dbm=-3 أو 0 (قراءة غير
    مكتملة من المودم) لأنها تظهر في السجلات وتعطي تصنيفاً مضللاً "ممتازة".
    """
    if not cells:
        return None
    dicts = [c for c in cells if isinstance(c, dict)]
    if not dicts:
        last = cells[-1]
        return last if isinstance(last, dict) else None

    registered = [c for c in dicts if c.get("registered")] or dicts

    def valid_dbm(cell):
        value = _extract_signal_metrics(cell)[0]
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        # نطاق dBm الواقعي لشبكات الخلوي: -199..-40 تقريباً
        return value if -200 < value <= -40 else None

    with_signal = [c for c in registered if valid_dbm(c) is not None]
    if with_signal:
        return max(with_signal, key=valid_dbm)

    try:
        return max(registered, key=lambda c: c.get("timestamp", 0))
    except (TypeError, ValueError):
        return registered[-1]


def _detect_network_type(best_cell):
    """تحديد نوع الشبكة الحالية من مفاتيح بيانات الخلية.

    يدعم الشكل الكامل (خلية تحتوي قسماً فرعياً مثل {"lte": {...}}) والشكل
    المبسّط الذي ترجعه بعض الإصدارات (خلية فيها مفتاح "type" مباشرة).
    """
    for key, label in NETWORK_TYPES.items():
        if key in best_cell:
            if key == "nr":
                nr = best_cell.get("nr") or {}
                # tac != -1 يعني شبكة غير مستقلة (NSA) تعتمد على LTE
                return "NR (5G)" if nr.get("tac") == -1 else "NR (5G NSA)"
            return label
    cell_type = str(best_cell.get("type", "")).lower()
    if cell_type in NETWORK_TYPES:
        return NETWORK_TYPES[cell_type]
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


def _as_dict(value):
    """إرجاع value إن كان dict، وإلا dict فارغ (يصلح مخرجات Termux غير المتوقعة)."""
    return value if isinstance(value, dict) else {}


def _cells_from_list(value):
    """تحويل قائمة عناصر قد تحتوي نصوصاً/أرقاماً إلى قوائم dicts قابلة للتحليل.

    بعض إصدارات termux-telephony-cellinfo تُرجع الخلية كنص خام مثل
    'dbm:-67,lac:4417,cid:6025,mcc:417,mnc:1' بدل كائن JSON — نفكّكه هنا.
    """
    cells = []
    for item in value or []:
        if isinstance(item, dict):
            cells.append(item)
        elif isinstance(item, str):
            parsed = {}
            for part in item.split(","):
                key, sep, val = part.partition(":")
                if sep:
                    key = key.strip()
                    val = val.strip()
                    parsed[key] = int(val) if val.lstrip("-").isdigit() else val
            if parsed:
                cells.append(parsed)
    return cells


def _normalize_cellular_payload(data):
    """توحيد أشكال مخرجات termux-telephony-cellinfo إلى (dict بيانات، خلايا).

    الأشكال المرصودة في السجلات:
      1. dict فيه cellInformation/telephonyManagerInformation (الشكل الكامل).
      2. مصفوفة dicts لكل خلية: {type, dbm, asu, cid, lac, mcc, mnc, psc}.
      3. نص خام داخل مصفوفة أو مفصول بفواصل — يفككه _cells_from_list.
    يرجع (data_dict, cells_list)؛ كلاهما قد يكون فارغاً لكن الشكل صالح.
    """
    if isinstance(data, dict):
        cell = _as_dict(data.get("cellInformation"))
        all_cells = _cells_from_list(cell.get("allCellInfo"))
        registered_cells = _cells_from_list(cell.get("registeredCellInfo"))
        return data, registered_cells or all_cells

    if isinstance(data, list):
        cells = _cells_from_list(data)
        # مصفوفة من العناصر غير المفهومة (نصوص بلا أزواج مفتاح:قيمة) → لا بيانات
        return {}, cells

    return {}, []


def _extract_dbm(best_cell):
    """استخراج قيمة dBm من الخلية مع دعم الأشكال المختلفة."""
    dbm_value, *_ = _extract_signal_metrics(best_cell)
    return dbm_value


def get_cellular_report():
    """إرجاع تقرير HTML كامل للشبكة الخلوية، أو None عند تعذر القراءة.

    يدعم شكل المخرجات الكامل (dict مع cellInformation) وكذلك الشكل المبسّط
    (مصفوفة خلايا مباشرة) الذي ترجعه بعض أجهزة/إصدارات Termux:API، فلا يعود
    فشل القراءة يُنتج رسالة غامضة أو يستثني المستخدم بخطأ Telegram.
    """
    output = run_termux_command(CELL_INFO_COMMAND)
    data = parse_json_output(output)
    if data is None:
        logger.warning("تعذر قراءة المعلومات الخلوية: %s", output)
        return None

    payload, source_cells = _normalize_cellular_payload(data)

    best_cell = _pick_best_cell(source_cells)
    signal_lines = build_signal_lines(best_cell)

    display_cells = len(source_cells)
    if display_cells:
        signal_lines += f"- <b>عدد الخلايا المرئية:</b> {display_cells}\n"

    # معلومات المشغل من TelephonyManager (قد تغيب في الشكل المبسّط)
    tm = _as_dict(payload.get("telephonyManagerInformation"))
    operator = tm.get("networkOperatorName") or tm.get("simOperatorName") or "غير متوفر"
    mcc_mnc = tm.get("networkOperator") or "غير متوفر"
    service_state = "متصل بالخدمة" if tm.get("serviceState") == 5 else str(
        tm.get("serviceState", "غير معروف")
    )

    usage = get_cellular_data_usage()

    # إذا لم نحصل على أي معلومة مفيدة إطلاقاً → نعتبر القراءة متعثرة
    has_signal = best_cell is not None and _extract_dbm(best_cell if isinstance(best_cell, dict) else {}) is not None
    has_operator = operator != "غير متوفر"
    if not has_signal and not has_operator:
        logger.warning("مخرجات خلوية بلا بيانات مفيدة: %s", output[:800])
        return None

    return (
        "📡 <b>معلومات الشبكة الخلوية:</b>\n"
        f"{signal_lines}"
        f"- <b>المشغل:</b> {html.escape(str(operator))} ({html.escape(str(mcc_mnc))})\n"
        f"- <b>حالة الخدمة:</b> {html.escape(service_state)}\n"
        f"{build_data_section(usage)}"
    )
