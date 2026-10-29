"""
Phone Status Monitor Bot — حزمة البوت المهيكلة.

كان المشروع سابقاً ملفاً واحداً (mybot_qwen1.py بأكثر من 1200 سطر)،
وقد أُعيدت هيكلة الكود إلى الحزم الفرعية التالية:

- phone_status_bot.core      : الإعدادات، السجلات، الأذونات، أدوات Termux/HTTP
- phone_status_bot.services  : الخدمات (البطارية، الكاميرا، الموقع، التسجيل...)
- phone_status_bot.handlers  : معالجات أوامر Telegram مقسّمة حسب المجال
- phone_status_bot.main      : نقطة الدخول وتجميع المعالجات وتشغيل البوت
"""

__version__ = "2.0.0"
