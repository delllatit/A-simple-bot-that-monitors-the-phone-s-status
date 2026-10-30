"""معالج أمر /ping لفحص اتصال الإنترنت."""

from phone_status_bot.core import config
from phone_status_bot.core.logging_setup import logger
from phone_status_bot.services.ping_service import (
    check_dns,
    check_icmp,
    check_tcp,
)


def _is_admin(user_id):
    """فلتر مسؤول — عدّله ليطابق نمط بقية المعالجات في مشروعك."""
    admin_id = getattr(config, "ADMIN_ID", None)
    admin_ids = getattr(config, "ADMIN_IDS", None)
    if admin_ids:
        return user_id in admin_ids
    return user_id == admin_id


def register(bot):

    @bot.message_handler(commands=["ping"])
    def handle_ping(message):
        if not _is_admin(message.from_user.id):
            bot.reply_to(message, "⛔ هذا الأمر مخصص للمسؤول.")
            return

        parts = (message.text or "").split(maxsplit=1)
        host = parts[1].strip() if len(parts) > 1 else "8.8.8.8"

        status = bot.reply_to(message, f"⏳ جاري فحص الاتصال بـ {host}...")

        try:
            icmp_ok, icmp_out, icmp_err = check_icmp(host)
            tcp_ok, tcp_ms = check_tcp("1.1.1.1", 53)
            dns_ok, dns_ms = check_dns("google.com")
        except Exception as e:
            logger.exception("فشل فحص ping: %s", e)
            bot.edit_message_text(
                f"❌ حدث خطأ أثناء الفحص: {e}",
                chat_id=status.chat.id,
                message_id=status.message_id,
            )
            return

        lines = [f"📡 *نتيجة فحص الاتصال* — `{host}`", ""]
        lines.append(f"ICMP (ping): {'✅' if icmp_ok else '❌'}")
        if icmp_out:
            tail = "\n".join(icmp_out.splitlines()[-3:])
            lines.append(f"```\n{tail}\n```")
        elif icmp_err:
            lines.append(f"  ↳ {icmp_err}")

        lines.append(
            "TCP (1.1.1.1:53): "
            + (f"✅ {tcp_ms:.0f} ms" if tcp_ok else "❌")
        )
        lines.append(
            "DNS (google.com): "
            + (f"✅ {dns_ms:.0f} ms" if dns_ok else "❌")
        )

        if not icmp_ok and tcp_ok and dns_ok:
            lines.append("\n⚠️ ICMP محجوب لكن الإنترنت يعمل (شائع في بعض الشبكات).")
        if not (tcp_ok or dns_ok):
            lines.append("\n❌ لا يوجد اتصال بالإنترنت.")

        text = "\n".join(lines)
        try:
            bot.edit_message_text(
                text,
                chat_id=status.chat.id,
                message_id=status.message_id,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning("فشل تعديل رسالة ping، إرسال نسخة جديدة: %s", e)
            bot.send_message(message.chat.id, text, parse_mode="Markdown")
