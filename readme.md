

# Phone Status Monitor Bot

A simple Telegram bot for Android/Termux that monitors the phone's battery and can report status, network details, GPS location, and take photos.

## Features

- Battery status and charging state
- Wi-Fi connection details
- Device IP information
- GPS location lookup
- Camera capture (front or back)
- Admin-only access control

## Requirements

- Python 3.8+
- Termux on Android
- Termux:API package
- `pyTelegramBotAPI`

## Setup

1. Install the required package in Termux:
   ```bash
   pkg install termux-api
   pip install pyTelegramBotAPI requests
