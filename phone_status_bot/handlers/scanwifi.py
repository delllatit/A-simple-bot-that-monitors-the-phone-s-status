import json
import subprocess

from phone_status_bot.core.logging_setup import logger


def register(bot):
    @bot.message_handler(commands=["scanwifi"])
    def scan_wifi(message):
        try:
            result = subprocess.run(
                ["termux-wifi-scaninfo"],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
            networks = json.loads(result.stdout or "[]")
        except FileNotFoundError:
            bot.reply_to(
                message,
                "أداة termux-wifi-scaninfo غير مثبتة.\n"
                "ثبّت حزمة termux-api: pkg install termux-api",
            )
            return
        except subprocess.TimeoutExpired:
            bot.reply_to(message, "انتهت مهلة تنفيذ المسح (15 ثانية).")
            return
        except subprocess.CalledProcessError as exc:
            logger.error("termux-wifi-scaninfo failed: %s", exc.stderr)
            bot.reply_to(message, f"تعذّر تنفيذ المسح:\n{exc.stderr or exc}")
            return
        except json.JSONDecodeError:
            bot.reply_to(message, "تعذّر تحليل بيانات الشبكات (JSON غير صالح).")
            return

        if not networks:
            bot.reply_to(
                message,
                "لا توجد نتائج مسح حالياً.\n"
                "💡 افتح إعدادات الواي فاي لبضع ثوانٍ لإجبار النظام على مسح جديد ثم أعد المحاولة.",
            )
            return

        # ترتيب حسب قوة الإشارة (الأقوى أولاً)
        networks.sort(key=lambda n: n.get("RSSI", -200), reverse=True)

        lines = [f"📶 الشبكات المرصودة ({len(networks)}):\n"]
        for net in networks:
            ssid = net.get("SSID") or "<مخفي>"
            bssid = net.get("BSSID", "-")
            rssi = net.get("RSSI", "?")
            freq = net.get("frequency", "?")
            lines.append(
                f"• {ssid}\n"
                f"   BSSID: {bssid}\n"
                f"   الإشارة: {rssi} dBm | التردد: {freq} MHz\n"
            )
        lines.append("\nℹ️ هذه نتائج آخر مسح أجراه النظام، وليست مسحاً فورياً.")

        bot.reply_to(message, "\n".join(lines))
