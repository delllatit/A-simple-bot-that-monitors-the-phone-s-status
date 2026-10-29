# ================== /whois ==================
# استخراج الحقول الأساسية من مخرجات whois، مع دعم تنسيقات شائعة:
#   netname, descr, org-name, orgname, organization, country

WHOIS_FIELD_ALIASES = {
    "netname": "netname",
    "descr": "descr",
    "description": "descr",
    "org-name": "org-name",
    "orgname": "org-name",
    "organization": "org-name",
    "country": "country",
    "country-name": "country",
    "net-name": "netname",
}


def _normalize_whois_field_name(raw_key):
    key = (raw_key or "").strip().lower().replace("_", "-")
    return WHOIS_FIELD_ALIASES.get(key, key)


def _extract_whois_fields(raw_output):
    """تصفية مخرجات whois إلى الحقول المطلوبة فقط مع إزالة التكرار."""
    results = []
    seen = set()

    for line in (raw_output or "").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue

        key_part, _, value_part = line.partition(":")
        key = _normalize_whois_field_name(key_part.strip())
        value = value_part.strip()

        if not key or not value:
            continue

        if key not in {"netname", "descr", "org-name", "country"}:
            continue

        entry = f"{key}: {value}"
        entry_key = entry.lower()
        if entry_key not in seen:
            seen.add(entry_key)
            results.append(entry)

    return results


@bot.message_handler(commands=["whois"])
@admin_only
def handle_whois(message):
    try:
        parts = (message.text or "").split()

        # إذا لم يُمرر أي عنوان، استخدم IP العام الحالي كما هو موضح في رسالة الأوامر
        if len(parts) == 1:
            try:
                resp = requests.get("https://api.ipify.org", timeout=10)
                resp.raise_for_status()
                target = resp.text.strip()
                is_public_ip = True
            except requests.RequestException:
                bot.reply_to(message, "❌ تعذر تحديد IP العام الحالي. استخدم /whois <عنوان IP>.")
                logger.exception("تعذر جلب IP العام لاستعلام whois")
                return
        elif len(parts) >= 2:
            arg = parts[1].strip()
            # التحقق من صحة المعرّف المسموح تمريره للأمر (IP/نطاق/مضيف) — منع حقن الأوامر
            if not re.fullmatch(r'[A-Za-z0-9._:-]+', arg):
                bot.reply_to(message, "❌ صيغة العنوان غير صحيحة.")
                return
            target = arg
            is_public_ip = False
        else:
            bot.reply_to(
                message,
                "الاستخدام: /whois <عنوان IP>\nمثال: /whois 8.8.8.8\n"
                "إذا لم تُحدد عنواناً سيُستخدم IP العام الحالي للجهاز.",
            )
            return

        # البحث عن أمر whois (متاح في Termux عبر: pkg install whois)
        whois_bin = shutil.which("whois")
        if not whois_bin:
            bot.reply_to(
                message,
                "❌ أمر whois غير مثبت. ثبّته عبر: pkg install whois",
            )
            logger.warning("أمر whois غير متوفر على الجهاز")
            return

        result = subprocess.run(
            [whois_bin, target],
            capture_output=True,
            text=True,
            timeout=30,
        )
        raw_output = result.stdout or ""
        fields = _extract_whois_fields(raw_output)

        header = f"🔎 نتائج whois للعنوان {target}"
        if is_public_ip:
            header += " (IP العام الحالي)"
        if not fields:
            summary = (result.stderr.strip() or "No matching records found")[:300]
            bot.reply_to(message, f"{header}\n\nلم يتم العثور على سجلات مطابقة.\n{summary}")
            logger.info("لا نتائج whois للعنوان %s", target)
            return

        body = "\n".join(fields)
        if len(body) > 4000:
            body = body[:4000] + "\n... (تم اقتطاع النتائج)"
        bot.reply_to(message, f"{header}\n\n{body}")
        logger.info("تم تنفيذ whois للعنوان %s للمستخدم %s", target, message.from_user.id)
    except subprocess.TimeoutExpired:
        logger.exception("انتهت مهلة أمر whois")
        bot.reply_to(message, "❌ انتهت مهلة استعلام whois (30 ثانية).")
    except requests.RequestException:
        logger.exception("تعذر جلب IP العام لاستعلام whois")
        bot.reply_to(message, "❌ تعذر تحديد IP العام الحالي. جرّب /whois <عنوان IP>.")
    except Exception:
        logger.exception("فشل في تنفيذ استعلام whois")
        bot.reply_to(message, "❌ تعذر تنفيذ استعلام whois. راجع سجل البوت.")

# ================== /selfie و /photo ==================
