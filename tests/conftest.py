"""Shared test setup: run the real Qt UI headlessly and keep config writes out of the repo."""
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pump(qapp):
    """Process Qt events for `ms` milliseconds (lets queued signals run)."""
    def _pump(ms: int = 50) -> None:
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.005)
    return _pump


@pytest.fixture
def qt_messages(qapp):
    """Collect every warning Qt prints (e.g. cross-thread timer misuse)."""
    from PyQt6.QtCore import qInstallMessageHandler
    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _mode, _ctx, msg: messages.append(msg))
    yield messages
    qInstallMessageHandler(previous)


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Point every reader/writer of config/api_keys.json at a temp file."""
    import ui
    from memory import config_manager

    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    path = cfg_dir / "api_keys.json"
    monkeypatch.setattr(ui, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(ui, "API_FILE", path)
    monkeypatch.setattr(config_manager, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(config_manager, "CONFIG_FILE", path)
    return path


@pytest.fixture
def jarvis_ui(qapp, config_file, pump):
    """The real JarvisUI facade, built headlessly against the temp config."""
    import ui
    j = ui.JarvisUI("face.png")
    pump(50)
    yield j
    j._win.close()
    j._win.deleteLater()
    pump(20)
