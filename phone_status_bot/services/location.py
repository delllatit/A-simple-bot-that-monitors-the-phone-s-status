"""خدمة الموقع: جلب إحداثيات GPS بأفضل دقة ممكنة عبر محاولات متعددة."""

import json
import subprocess
import time

from phone_status_bot.core.logging_setup import logger

GPS_ATTEMPTS = 3
GPS_TIMEOUT = 20
GPS_RETRY_DELAY = 2
GOOD_ENOUGH_ACCURACY = 20  # متر


def fetch_gps_location():
    """إجراء حتى 3 محاولات لقراءة GPS وإرجاع أفضل قراءه (أدق accuracy).

    يرجع dict فيه latitude/longitude/accuracy أو None عند التعذر.
    """
    best_location = None

    for attempt in range(GPS_ATTEMPTS):
        try:
            result = subprocess.run(
                ["termux-location", "-p", "gps", "-r", "once"],
                capture_output=True,
                text=True,
                timeout=GPS_TIMEOUT,
            )
            if result.returncode != 0:
                continue

            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                continue

            lat = data.get("latitude")
            lon = data.get("longitude")
            accuracy = data.get("accuracy")

            if lat is None or lon is None or accuracy is None:
                continue

            candidate = {"latitude": lat, "longitude": lon, "accuracy": float(accuracy)}
            if best_location is None or candidate["accuracy"] < best_location["accuracy"]:
                best_location = candidate

            if candidate["accuracy"] <= GOOD_ENOUGH_ACCURACY:
                break
        except Exception:
            pass

        if attempt < GPS_ATTEMPTS - 1:
            time.sleep(GPS_RETRY_DELAY)

    return best_location


def format_location_report(location):
    """تنسيق رسالة الموقع مع رابط الخريطة والدقة."""
    lat = location["latitude"]
    lon = location["longitude"]
    accuracy = location["accuracy"]
    maps_url = f"https://maps.google.com/?q={lat},{lon}"
    return (
        f"📍 موقع الهاتف\nخط العرض: {lat}\nخط الطول: {lon}\n"
        f"🎯 الدقة المقدرة: ±{accuracy:.1f} متر\n🗺️ الخريطة: {maps_url}"
    )


def get_best_location_or_none(user_id=None):
    """جلب الموقع مع تسجيل الفشل (تُستخدم من المعالج في خيط منفصل)."""
    location = fetch_gps_location()
    if location is None and user_id is not None:
        logger.warning("لم يتم الحصول على موقع GPS للمستخدم %s", user_id)
    return location
