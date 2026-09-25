import os
import platform
import shlex
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

_CNW: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if platform.system() == "Windows" else {}
)

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_os() -> str:
    _sys = platform.system()
    if _sys == "Darwin":
        return "mac"
    if _sys == "Linux":
        return "linux"
    return "windows"


def _scripts_dir() -> Path:
    d = Path.home() / ".jarvis" / "reminders"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sanitise(text: str, max_len: int = 200) -> str:
    return (
        text.replace("\\", "")
            .replace('"', "")
            .replace("'", "")
            .replace("\n", " ")
            .replace("\r", "")
            .strip()
    )[:max_len]

def _write_notify_script(task_name: str, message: str, os_name: str,
                         target_year: int | None = None) -> Path:
    script_path = _scripts_dir() / f"{task_name}.py"
    # repr keeps emoji intact; json.dumps wrote them as surrogate pairs, which
    # notify-send/osascript arguments cannot encode, so nothing was shown.
    msg_literal = repr(message)

    if os_name == "windows":
        notify_block = f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="J.A.R.V.I.S Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        from win10toast import ToastNotifier
        ToastNotifier().show_toast("J.A.R.V.I.S Reminder", message, duration=15, threaded=False)
        notified = True
    except Exception:
        pass

if not notified:
    try:
        import subprocess
        notified = subprocess.run(["msg", "*", "/TIME:30", message], check=False).returncode == 0
    except Exception:
        pass

if not notified:
    try:
        import ctypes   # present on every Windows edition
        ctypes.windll.user32.MessageBoxW(0, message, "J.A.R.V.I.S Reminder", 0x40 | 0x40000)
    except Exception:
        pass

try:
    import winsound
    for freq in [800, 1000, 1200]:
        winsound.Beep(freq, 180)
        import time; time.sleep(0.08)
except Exception:
    pass
"""

    elif os_name == "mac":
        notify_block = f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="J.A.R.V.I.S Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        import subprocess
        script = 'display notification "{{}}" with title "J.A.R.V.I.S Reminder"'.format(
            message.replace('"', '')
        )
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception:
        pass
"""

    else:  # linux
        notify_block = f"""
message = {msg_literal}
notified = False

try:
    from plyer import notification
    notification.notify(title="J.A.R.V.I.S Reminder", message=message, timeout=15)
    notified = True
except Exception:
    pass

if not notified:
    try:
        import subprocess
        subprocess.run(
            ["notify-send", "--urgency=normal", "--expire-time=15000",
             "J.A.R.V.I.S Reminder", message],
            check=False
        )
    except Exception:
        pass
"""

    # A fired reminder must unregister itself: launchd ignores StartCalendarInterval's
    # Year, so a macOS reminder re-fired every year; Windows tasks and systemd
    # timers piled up.
    if os_name == "windows":
        cleanup = f'subprocess.run(["schtasks", "/Delete", "/TN", {task_name!r}, "/F"], capture_output=True)'
    elif os_name == "mac":
        label = f"com.jarvis.reminder.{task_name}"
        cleanup = (f'(pathlib.Path.home() / "Library" / "LaunchAgents" / "{label}.plist").unlink(missing_ok=True)\n'
                   f'    subprocess.run(["launchctl", "remove", {label!r}], capture_output=True)')
    else:
        cleanup = (f'units = pathlib.Path(os.environ.get("XDG_CONFIG_HOME") or pathlib.Path.home() / ".config") / "systemd" / "user"\n'
                   f'    subprocess.run(["systemctl", "--user", "disable", "{task_name}.timer"], capture_output=True)\n'
                   f'    (units / "{task_name}.timer").unlink(missing_ok=True)\n'
                   f'    (units / "{task_name}.service").unlink(missing_ok=True)')
    year_guard = ""
    if os_name == "mac" and target_year:
        # ...and a reminder set 11+ months ahead would fire a year early.
        year_guard = f"import datetime\nif datetime.date.today().year != {int(target_year)}:\n    sys.exit(0)\n"

    script_body = f"""# Auto-generated by J.A.R.V.I.S reminder — do not edit
import sys, os, pathlib
{year_guard}{notify_block}
# Unregister, then self-delete after firing
try:
    import subprocess
    {cleanup}
except Exception:
    pass
try:
    pathlib.Path(__file__).unlink(missing_ok=True)
except Exception:
    pass
"""
    script_path.write_text(script_body, encoding="utf-8")
    script_path.chmod(0o600)   # owner read/write only
    return script_path

def _schedule_windows(target_dt: datetime, task_name: str,
                      script_path: Path, message: str) -> str:
    python_exe = Path(sys.executable)
    pythonw = python_exe.parent / "pythonw.exe"
    if pythonw.exists():
        python_exe = pythonw

    xml_path = _scripts_dir() / f"{task_name}.xml"
    xml_content = (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        '  <RegistrationInfo><Description>J.A.R.V.I.S Reminder</Description></RegistrationInfo>\n'
        '  <Triggers><TimeTrigger>\n'
        f'    <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>\n'
        '    <Enabled>true</Enabled>\n'
        '  </TimeTrigger></Triggers>\n'
        '  <Actions><Exec>\n'
        f'    <Command>{python_exe}</Command>\n'
        f'    <Arguments>"{script_path}"</Arguments>\n'
        '  </Exec></Actions>\n'
        '  <Settings>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n'
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n'
        '    <StartWhenAvailable>true</StartWhenAvailable>\n'
        '    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>\n'
        '    <Enabled>true</Enabled>\n'
        '  </Settings>\n'
        '  <Principals><Principal>\n'
        '    <LogonType>InteractiveToken</LogonType>\n'
        '    <RunLevel>LeastPrivilege</RunLevel>\n'
        '  </Principal></Principals>\n'
        '</Task>'
    )

    xml_path.write_text(xml_content, encoding="utf-16")

    result = subprocess.run(
        ["schtasks", "/Create", "/TN", task_name, "/XML", str(xml_path), "/F"],
        capture_output=True, text=True, **_CNW,
    )

    try:
        xml_path.unlink(missing_ok=True)
    except Exception:
        pass

    if result.returncode != 0:
        script_path.unlink(missing_ok=True)
        err = (result.stderr or result.stdout).strip()
        print(f"[Reminder] ❌ schtasks: {err}")
        return ""  

    return task_name


def _schedule_mac(target_dt: datetime, task_name: str,
                  script_path: Path) -> str:
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    label     = f"com.jarvis.reminder.{task_name}"
    plist_path = agents_dir / f"{label}.plist"

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>{label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{sys.executable}</string>
    <string>{script_path}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Year</key>   <integer>{target_dt.year}</integer>
    <key>Month</key>  <integer>{target_dt.month}</integer>
    <key>Day</key>    <integer>{target_dt.day}</integer>
    <key>Hour</key>   <integer>{target_dt.hour}</integer>
    <key>Minute</key> <integer>{target_dt.minute}</integer>
  </dict>
  <key>RunAtLoad</key>         <false/>
  <key>StandardOutPath</key>   <string>/dev/null</string>
  <key>StandardErrorPath</key> <string>/dev/null</string>
</dict>
</plist>
"""
    plist_path.write_text(plist_content, encoding="utf-8")
    plist_path.chmod(0o644)

    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True, text=True,
    )

    if result.returncode != 0:
        plist_path.unlink(missing_ok=True)
        script_path.unlink(missing_ok=True)
        print(f"[Reminder] ❌ launchctl: {result.stderr.strip()}")
        return ""

    return label


def _schedule_linux(target_dt: datetime, task_name: str,
                    script_path: Path) -> str:

    if shutil.which("systemctl"):
        # Real unit files with Persistent=true: a systemd-run timer is transient
        # and silently vanished on reboot or logout. Persistent also fires a
        # reminder that came due while the machine was off, once it is back.
        on_calendar = target_dt.strftime("%Y-%m-%d %H:%M:00")
        unit_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        service, timer = unit_dir / f"{task_name}.service", unit_dir / f"{task_name}.timer"

        def q(arg) -> str:          # systemd quoting; % starts a specifier
            return '"' + str(arg).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
        service.write_text("[Unit]\nDescription=JARVIS reminder\n\n[Service]\nType=oneshot\n"
                           f"ExecStart={q(sys.executable)} {q(script_path)}\n", encoding="utf-8")
        timer.write_text("[Unit]\nDescription=JARVIS reminder\n\n[Timer]\n"
                         f"OnCalendar={on_calendar}\nPersistent=true\n\n"
                         "[Install]\nWantedBy=timers.target\n", encoding="utf-8")
        ok = all(subprocess.run(cmd, capture_output=True, text=True).returncode == 0 for cmd in (
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", timer.name],
        ))
        if ok:
            return task_name
        service.unlink(missing_ok=True)
        timer.unlink(missing_ok=True)
        print("[Reminder] ⚠️ systemd user timer failed, trying 'at'")

    if shutil.which("at"):
        at_time = target_dt.strftime("%H:%M %Y-%m-%d")
        cmd_str = f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))}\n"
        result  = subprocess.run(
            ["at", at_time],
            input=cmd_str, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return task_name
        print(f"[Reminder] ❌ at: {result.stderr.strip()}")
        return ""

    print("[Reminder] ❌ Neither systemd-run nor at found on this Linux system.")
    return ""

def reminder(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:

    date_str = parameters.get("date", "").strip()
    time_str = parameters.get("time", "").strip()
    message  = parameters.get("message", "Reminder").strip()

    if not date_str or not time_str:
        return "I need both a date and a time to set a reminder."

    try:
        target_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return "I couldn't parse that date or time. Please use YYYY-MM-DD and HH:MM."

    if target_dt <= datetime.now():
        return "That time has already passed — I can't set a reminder in the past."

    os_name    = _get_os()
    safe_msg   = _sanitise(message)
    task_name  = f"JARVISReminder_{target_dt.strftime('%Y%m%d_%H%M')}_{uuid.uuid4().hex[:8]}"

    try:
        script_path = _write_notify_script(task_name, safe_msg, os_name, target_dt.year)
    except Exception as e:
        return f"Could not prepare the reminder script: {e}"

    try:
        if os_name == "windows":
            job_id = _schedule_windows(target_dt, task_name, script_path, safe_msg)
        elif os_name == "mac":
            job_id = _schedule_mac(target_dt, task_name, script_path)
        else:
            job_id = _schedule_linux(target_dt, task_name, script_path)
    except Exception as e:
        script_path.unlink(missing_ok=True)
        print(f"[Reminder] ❌ Scheduling exception: {e}")
        return "Something went wrong while scheduling the reminder."

    if not job_id:
        script_path.unlink(missing_ok=True)
        return "I couldn't register the reminder with the system scheduler."

    if player:
        player.write_log(f"[Reminder] ✅ {date_str} {time_str} — {safe_msg[:40]}")

    friendly_time = target_dt.strftime("%B %d at %I:%M %p")
    return f"Reminder set for {friendly_time}."


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "reminder",
    "description": "Sets a timed reminder using Task Scheduler.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "date": {
                "type": "STRING",
                "description": "Date in YYYY-MM-DD format"
            },
            "time": {
                "type": "STRING",
                "description": "Time in HH:MM format (24h)"
            },
            "message": {
                "type": "STRING",
                "description": "Reminder message text"
            }
        },
        "required": [
            "date",
            "time",
            "message"
        ]
    },
    "handler": reminder,
}
