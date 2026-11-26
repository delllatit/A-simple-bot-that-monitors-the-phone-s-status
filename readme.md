# Phone Status Bot

A small Telegram bot that runs on your own Android phone (inside [Termux](https://termux.dev)) and lets you check on the phone and control it remotely from Telegram. Useful for checking battery, network and location, finding a lost phone, and running quick actions without touching the device.

> **Own devices only.** Run this only on a phone you own, with your own Telegram bot token. Only Telegram IDs listed in `ADMIN_ID` can use it. Do not install it on anyone else's phone without their knowledge and consent.

## Features

- **Status:** battery (with low-battery alerts), CPU and memory, storage, uptime, bot status
- **Network:** Wi-Fi info and switching, cellular signal, hotspot and Bluetooth on/off, IP address, whois lookup, ping
- **Location:** current GPS location, plus a **lost mode** that sends the location every N minutes (1 to 120) until stopped and survives reboots
- **Find my phone:** ring, tone, flash, vibrate
- **Camera and screen:** front/back photo, screenshot, audio recording (`/record`, `/stop`)
- **Phone:** contacts list, place a call, send SMS, set clipboard text
- **Security:** admin-only commands, rate limiting, and an alert to the admins when someone else tries to use the bot
- **Reliability:** retry with backoff, persistent outbox for messages that fail while offline, rotating log file

## Requirements

- Android phone with [Termux](https://termux.dev) and the **Termux:API** app (grant camera, location, microphone, SMS, contacts permissions as needed)
- Python 3
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Your own numeric Telegram user ID

## Installation

```bash
pkg update && pkg install python git termux-api
git clone https://github.com/delllatit/A-simple-bot-that-monitors-the-phone-s-status.git
cd A-simple-bot-that-monitors-the-phone-s-status
pip install -r requirements.txt
cp .env.example .env
```

## Configuration

Edit `.env`:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token from BotFather |
| `ADMIN_ID` | Telegram user ID(s) allowed to use the bot |
| `BOT_LOG_FILE` | Path of the log file |
| `BATTERY_CHECK_INTERVAL` | Seconds between battery checks (default 1800) |
| `RECORD_MAX_SECONDS` | Max length of an audio recording (default 600) |
| `RATE_LIMIT_WINDOW` | Seconds between commands per user (default 3) |
| `SMS_SECRET` | Secret for the local SMS gateway. Generate with `python -c "import secrets; print(secrets.token_hex(16))"` |
| `SMS_GATEWAY_PORT` | Port of the local SMS gateway (default 8765, listens on 127.0.0.1 only) |
| `SMS_RATE_MAX` / `SMS_RATE_WINDOW` | Rate limit for the SMS gateway |

Never commit your real `.env`. It is already in `.gitignore`.

## Usage

```bash
python -m phone_status_bot.main
```

(`python mybot_qwen1.py` still works for the old entry point.) Then send `/start` to your bot in Telegram.

### Commands

| Command | What it does |
|---|---|
| `/start`, `/help` | Show the command list |
| `/battery` | Battery info |
| `/network`, `/wifi` | Wi-Fi info, view or change network |
| `/cellular` | Cellular signal and data |
| `/hotspot on\|off`, `/bluetooth on\|off` | Toggle hotspot or Bluetooth |
| `/ping`, `/ip`, `/whois` | Connectivity, IP addresses, IP owner info |
| `/location` | Current GPS location |
| `/ring`, `/tone`, `/flash`, `/vibrate` | Make the phone easy to find |
| `/selfie`, `/photo` | Front or back camera photo |
| `/screenshot` | Screenshot |
| `/record`, `/stop` | Start audio recording, stop and send it |
| `/clipboard` | Put text in the phone clipboard |
| `/contacts`, `/call`, `/sms` | Contacts, call, send SMS |
| `/storage`, `/cpu`, `/uptime`, `/status` | System and bot status |
| `/admins`, `/capabilities` | Approved admins, what this device supports |

Lost mode and alert settings have their own commands; see `/help` in the bot.

## Project layout

```
phone_status_bot/
  main.py        entry point and polling loop
  core/          config, state, permissions, Termux helpers, outbox
  handlers/      Telegram command handlers
  services/      battery, location, tracking, camera, Wi-Fi, SMS gateway, alerts
mybot_qwen1.py   legacy entry point
```

## Security notes

- Keep the bot token and `.env` private. If the token leaks, revoke it in BotFather.
- Keep `ADMIN_ID` limited to yourself. Anyone in that list can see your location, camera and SMS.
- Use a Telegram account with two-step verification.

## License

Add a license of your choice (for example MIT) as a `LICENSE` file.

---

## &#1576;&#1575;&#1604;&#1593;&#1585;&#1576;&#1610; (&#1605;&#1604;&#1582;&#1589;)

&#1576;&#1608;&#1578; &#1578;&#1610;&#1604;&#1610;&#1580;&#1585;&#1575;&#1605; &#1576;&#1587;&#1610;&#1591; &#1610;&#1593;&#1605;&#1604; &#1593;&#1604;&#1609; &#1607;&#1575;&#1578;&#1601;&#1603; &#1575;&#1604;&#1571;&#1606;&#1583;&#1585;&#1608;&#1610;&#1583; &#1593;&#1576;&#1585; Termux&#1548; &#1610;&#1578;&#1610;&#1581; &#1604;&#1603; &#1605;&#1585;&#1575;&#1602;&#1576;&#1577; &#1607;&#1575;&#1578;&#1601;&#1603; &#1608;&#1575;&#1604;&#1578;&#1581;&#1603;&#1605; &#1576;&#1607; &#1593;&#1606; &#1576;&#1593;&#1583;: &#1575;&#1604;&#1576;&#1591;&#1575;&#1585;&#1610;&#1577;&#1548; &#1575;&#1604;&#1588;&#1576;&#1603;&#1577;&#1548; &#1575;&#1604;&#1605;&#1608;&#1602;&#1593;&#1548; &#1608;&#1590;&#1593; &#1575;&#1604;&#1578;&#1578;&#1576;&#1617;&#1593; &#1593;&#1606;&#1583; &#1575;&#1604;&#1590;&#1610;&#1575;&#1593;&#1548; &#1575;&#1604;&#1585;&#1606;&#1610;&#1606;&#1548; &#1575;&#1604;&#1603;&#1575;&#1605;&#1610;&#1585;&#1575;&#1548; &#1604;&#1602;&#1591;&#1577; &#1575;&#1604;&#1588;&#1575;&#1588;&#1577;&#1548; &#1575;&#1604;&#1578;&#1587;&#1580;&#1610;&#1604; &#1575;&#1604;&#1589;&#1608;&#1578;&#1610;&#1548; &#1575;&#1604;&#1585;&#1587;&#1575;&#1574;&#1604; &#1608;&#1575;&#1604;&#1605;&#1603;&#1575;&#1604;&#1605;&#1575;&#1578;.

**&#1575;&#1604;&#1578;&#1588;&#1594;&#1610;&#1604;:** &#1579;&#1576;&#1617;&#1578; Termux &#1608; Termux:API&#1548; &#1579;&#1605; `pip install -r requirements.txt`&#1548; &#1608;&#1575;&#1606;&#1587;&#1582; `.env.example` &#1573;&#1604;&#1609; `.env` &#1608;&#1590;&#1593; &#1578;&#1608;&#1603;&#1606; &#1575;&#1604;&#1576;&#1608;&#1578; &#1605;&#1606; BotFather &#1608;&#1605;&#1593;&#1585;&#1617;&#1601;&#1603; &#1601;&#1610; `ADMIN_ID`&#1548; &#1579;&#1605; &#1588;&#1594;&#1617;&#1604; `python -m phone_status_bot.main`.

**&#1578;&#1606;&#1576;&#1610;&#1607;:** &#1575;&#1587;&#1578;&#1582;&#1583;&#1605;&#1607; &#1593;&#1604;&#1609; &#1607;&#1575;&#1578;&#1601;&#1603; &#1571;&#1606;&#1578; &#1601;&#1602;&#1591;. &#1604;&#1575; &#1578;&#1590;&#1593; &#1605;&#1593;&#1585;&#1617;&#1601; &#1571;&#1610; &#1588;&#1582;&#1589; &#1601;&#1610; `ADMIN_ID` &#1573;&#1604;&#1575; &#1573;&#1584;&#1575; &#1603;&#1606;&#1578; &#1578;&#1579;&#1602; &#1576;&#1607;&#1548; &#1608;&#1604;&#1575; &#1578;&#1606;&#1588;&#1585; &#1605;&#1604;&#1601; `.env` &#1571;&#1576;&#1583;&#1575;&#1611;.
