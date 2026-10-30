
# Phone Status Monitor Bot

A simple Telegram bot designed to run on Android devices via Termux. It allows you to monitor the phone's status and collect useful device information such as battery level, network details, location, IP information, and media related data.

This project is intended for educational, testing, and authorized device monitoring use cases only. It interacts with sensitive Android features, so it must be used responsibly and only on devices you own or are explicitly authorized to monitor.

> Important: This project can access sensitive permissions such as camera, GPS, contacts, SMS, calls, and microphone. Use it only with proper consent and in compliance with local laws and privacy policies.

## Features

- Battery status and charging information
- Wi-Fi details
- Cellular network information
- Local and public IP address
- GPS-based current location
- Front or rear camera photo capture
- Contact list access
- SMS sending
- Phone call initiation
- Audio recording with automatic stop
- Bot uptime and status monitoring
- Admin management via `ADMIN_ID`
- System information such as storage and CPU usage

## Requirements

- Android device
- Termux installed
- Termux:API package
- Python 3.8 or newer
- Telegram Bot Token
- Telegram user ID for the admin

## Installation

### 1) Install Termux and required packages

```bash
pkg update && pkg upgrade
pkg install termux-api git python
```

### 2) Clone the repository

```bash
git clone https://github.com/delllatit/A-simple-bot-that-monitors-the-phone-s-status.git
cd A-simple-bot-that-monitors-the-phone-s-status
```

### 3) Install Python dependencies

```bash
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root and add the following values:

```env
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_ID=YOUR_ADMIN_TELEGRAM_ID
BOT_LOG_FILE=/data/data/com.termux/files/home/bot-logs/mybot.log
BATTERY_CHECK_INTERVAL=1800
RECORD_MAX_SECONDS=600
RATE_LIMIT_WINDOW=3
```

### Configuration Notes

- `TELEGRAM_BOT_TOKEN`: Your Telegram bot token from BotFather
- `ADMIN_ID`: One or more admin Telegram IDs separated by commas
- `BOT_LOG_FILE`: Log file path
- `BATTERY_CHECK_INTERVAL`: Battery monitoring interval in seconds
- `RECORD_MAX_SECONDS`: Max audio recording duration
- `RATE_LIMIT_WINDOW`: Rate limit window in seconds

## Project Structure

```text
A-simple-bot-that-monitors-the-phone-s-status/
├── mybot_qwen1.py
├── requirements.txt
├── readme.md
├── .gitignore
└── phone_status_bot/
    ├── __init__.py
    ├── main.py
    ├── core/
    │   ├── config.py
    │   ├── permissions.py
    │   ├── state.py
    │   ├── termux.py
    │   ├── logging_setup.py
    │   └── html_utils.py
    ├── handlers/
    ├── services/
    └── ...
```

## Running the Bot

You can start the bot using either of these commands:

```bash
python -m phone_status_bot.main
```

or:

```bash
python mybot_qwen1.py
```

## Available Commands

- `/start` — Start the bot and show available commands
- `/help` — Show command list
- `/battery` — Battery details
- `/network` — Wi-Fi information
- `/cellular` — Cellular signal details
- `/location` — Current GPS location
- `/ip` — Local and public IP information
- `/whois` — IP owner lookup
- `/record` — Start voice recording
- `/stop` — Stop and send the recording
- `/sms` — Send an SMS
- `/uptime` — Bot runtime
- `/status` — Bot status
- `/admins` — Admin list
- `/storage` — Disk usage
- `/cpu` — CPU and memory usage
- `/contacts` — Contacts list
- `/call` — Place a call

## Security and Privacy Warning

This bot can access and control features that may be considered highly sensitive, including:

- Camera
- GPS/location
- Contacts
- SMS messages
- Phone calls
- Microphone recording

Use this project only if you:

- Own the device
- Have explicit permission from the owner
- Follow all applicable laws and privacy requirements
- Understand the security implications of running access-control tools

## Notes

The project was originally implemented as a single large Python file, but it has been reorganized into a more maintainable package structure under `phone_status_bot` for better code management and modularity.

## License

This project is shared for educational and technical experimentation purposes. Please check whether the repository includes a specific license before using it in production or public deployment environments.
```

### 1) تثبيت Termux:API

```bash
pkg update && pkg upgrade
pkg install termux-api git python
