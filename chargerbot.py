import json, subprocess, time, urllib.request, urllib.parse

TOKEN = "8898669871:AAGDfptV9l4A5C9aUyZUmK2i0-xTPd1JbRU"
CHAT_ID = "6002823280"

def send(text):
    url = ("https://api.telegram.org/bot" + TOKEN + "/sendMessage"
           "?chat_id=" + CHAT_ID + "&text=" + urllib.parse.quote(text))
    urllib.request.urlopen(url)

last = "UNPLUGGED"
print("مراقب الشحن شغال...")
while True:
    try:
        status = json.loads(
            subprocess.check_output(["termux-battery-status"]))["plugged"]
        if status != "UNPLUGGED" and last == "UNPLUGGED":
            send("⚡ الهاتف وُصل بالشاحن!")
        last = status
    except Exception:
        pass
    time.sleep(15)
