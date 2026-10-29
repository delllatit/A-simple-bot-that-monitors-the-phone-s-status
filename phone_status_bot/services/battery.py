"""خدمة مراقبة البطارية في الخلفية مع تنبيه العتبات، وتقرير /battery."""

import html
import json
import subprocess

from phone_status_bot.core import config, state
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.core.permissions import safe_send
from phone_status_bot.core.termux import run_termux_command, parse_json_output

BATTERY_STATUS_COMMAND = ["termux-battery-status"]


def get_battery_report():
    """تقرير البطارية الكامل بصيغة HTML لأمر /battery، أو None عند تعذر القراءة."""
    output = run_termux_command(BATTERY_STATUS_COMMAND)
    data = parse_json_output(output)
    if not isinstance(data, dict):
        logger.warning("تعذر قراءة بطارية: %s", output)
        return None
    return (
        "🔋 <b>معلومات البطارية:</b>\n"
        f"- <b>النسبة:</b> {html.escape(str(data.get('percentage', 'N/A')))}%\n"
        f"- <b>الحالة:</b> {html.escape(str(data.get('status', 'N/A')))}\n"
        f"- <b>الشحن:</b> {html.escape(str(data.get('plugged', 'N/A')))}\n"
        f"- <b>الصحة:</b> {html.escape(str(data.get('health', 'N/A')))}\n"
        f"- <b>الحرارة:</b> {html.escape(str(data.get('temperature', 'N/A')))} °C\n"
        f"- <b>التيار:</b> {html.escape(str(data.get('current', 'N/A')))} mA"
    )

# حالة داخلية لمنع تكرار تنبيه عدم توفر termux-api
_battery_api_warned = False

RESET_MARGIN_PERCENT = 5  # هامش فوق أعلى عتبة لمنع وميض إعادة التنبيه


def read_battery_status():
    """قراءة حالة البطارية عبر termux-battery-status؛ يرجع dict أو None."""
    result = subprocess.run(
        ["termux-battery-status"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        return json.loads(result.stdout)
    return None


def evaluate_thresholds(percentage, alerted):
    """تحديد العتبات الجديدة التي يجب التنبيه عليها وتحديث مجموعة المُنبَّه.

    ترجع قائمة العتبات المستحقة للتنبيه هذه الجولة.
    """
    due = []
    for threshold in config.BATTERY_THRESHOLDS:
        if percentage < threshold and threshold not in alerted:
            due.append(threshold)
            alerted.add(threshold)

    # إعادة الضبط عند الشحن فوق أعلى عتبة + الهامش (لمنع الوميض حول العتبة)
    if percentage >= config.BATTERY_THRESHOLDS[0] + RESET_MARGIN_PERCENT:
        alerted.clear()

    return due


def battery_monitor():
    """حلقة المراقبة الرئيسية — تعمل في خيط خلفي حتى يتم حدث SHUTDOWN."""
    global _battery_api_warned
    alerted_thresholds = set()

    while not state.SHUTDOWN.is_set():
        try:
            data = read_battery_status()
            if data is not None:
                _battery_api_warned = False  # إعادة الضبط عند النجاح
                percentage = data.get("percentage")
                if percentage is not None:
                    for threshold in evaluate_thresholds(percentage, alerted_thresholds):
                        for admin_id in config.ADMIN_IDS:
                            safe_send(
                                admin_id,
                                f"⚠️ <b>تنبيه البطارية:</b>\nالنسبة الحالية: {percentage}%\n"
                                f"(وصلت إلى أقل من {threshold}%)",
                                parse_mode="HTML",
                            )
        except FileNotFoundError:
            # تنبيه مرة واحدة فقط إذا كان termux-api غير مثبت
            if not _battery_api_warned:
                _battery_api_warned = True
                for admin_id in config.ADMIN_IDS:
                    safe_send(
                        admin_id,
                        "⚠️ termux-api غير مثبت أو termux-battery-status غير متاح. "
                        "تنبيهات البطارية معطلة حتى إصلاح ذلك."
                    )
                logger.error("termux-battery-status غير موجود أو غير مثبت")
        except Exception as e:
            logger.error("خطأ في مراقبة البطارية: %s", e)

        # انتظار فترة الفحص مع الاستجابة السريعة للإيقاف
        state.SHUTDOWN.wait(config.BATTERY_CHECK_INTERVAL)
