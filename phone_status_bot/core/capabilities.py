# core/capabilities.py
import subprocess, shutil, json

def _run(cmd, t=5):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=t)
    except Exception:
        return None

def detect():
    caps = {}
    r = _run(["getprop", "ro.build.version.sdk"])
    caps["sdk"] = int(r.stdout.strip()) if r and r.stdout.strip().isdigit() else 0
    caps["termux_api"] = shutil.which("termux-battery-status") is not None
    # الـ API نفسه شغال؟ (التطبيق مثبت ومعه صلاحيات)
    r = _run(["termux-battery-status"], 8)
    caps["termux_api_ok"] = bool(r and r.returncode == 0 and r.stdout.strip().startswith("{"))
    r = _run(["su", "-c", "id"], 5)
    caps["root"] = bool(r and r.returncode == 0 and "uid=0" in r.stdout)
    caps["proc_stat"] = _readable("/proc/stat")
    return caps
