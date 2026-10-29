#!/usr/bin/env python3
"""نقطة تشغيل متوافقة مع الاسم القديم للمشروع.

كان هذا الملف يحتوي على البوت كاملاً في ملف واحد (أكثر من 1200 سطر)،
وقد أُعيدت هيكلة الكود إلى الحزمة phone_status_bot:

- phone_status_bot.core      : الإعدادات، السجلات، الأذونات، أدوات Termux/HTTP
- phone_status_bot.services  : منطق العمل (بطارية، كاميرا، شبكة، موقع، تسجيل...)
- phone_status_bot.handlers  : معالجات أوامر Telegram مقسّمة حسب المجال
- phone_status_bot.main      : نقطة الدخول وتجميع المعالجات وتشغيل البوت

شغّل مباشرةً عبر:  python mybot_qwen1.py
أو حديثاً عبر:     python -m phone_status_bot.main
"""

from phone_status_bot.main import main

if __name__ == "__main__":
    main()
