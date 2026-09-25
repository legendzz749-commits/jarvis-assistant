"""Regression tests: every reminder keeps its own task and message."""
from datetime import datetime, timedelta

from actions import reminder as rm


def test_two_reminders_in_the_same_minute_do_not_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "_scripts_dir", lambda: tmp_path)
    monkeypatch.setattr(rm, "_get_os", lambda: "linux")
    scheduled = []
    monkeypatch.setattr(rm, "_schedule_linux",
                        lambda dt, name, script: scheduled.append((name, script)) or name)
    when = datetime.now() + timedelta(days=1)
    day, hhmm = when.strftime("%Y-%m-%d"), when.strftime("%H:%M")

    rm.reminder({"date": day, "time": hhmm, "message": "Call mum"})
    rm.reminder({"date": day, "time": hhmm, "message": "Take pills"})

    (name1, script1), (name2, script2) = scheduled
    assert name1 != name2
    assert "Call mum" in script1.read_text() and "Take pills" in script2.read_text()


def test_windows_notifier_script_is_valid_python(tmp_path, monkeypatch):
    monkeypatch.setattr(rm, "_scripts_dir", lambda: tmp_path)
    script = rm._write_notify_script("JARVISReminder_x", "Stand up", "windows")
    compile(script.read_text(), str(script), "exec")
    assert "MessageBoxW" in script.read_text()


def test_linux_reminder_survives_a_reboot(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(rm.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls = []
    monkeypatch.setattr(rm.subprocess, "run",
                        lambda argv, **k: calls.append(argv) or SimpleNamespace(returncode=0, stderr=""))
    script = tmp_path / "My Reminders" / "r.py"

    name = rm._schedule_linux(datetime(2030, 1, 2, 9, 30), "JARVISReminder_x", script)

    timer = (tmp_path / "systemd" / "user" / "JARVISReminder_x.timer").read_text()
    service = (tmp_path / "systemd" / "user" / "JARVISReminder_x.service").read_text()
    assert name == "JARVISReminder_x"
    assert "Persistent=true" in timer and "OnCalendar=2030-01-02 09:30:00" in timer
    assert f'"{script}"' in service                      # quoted: the path has a space
    assert ["systemctl", "--user", "enable", "--now", "JARVISReminder_x.timer"] in calls
