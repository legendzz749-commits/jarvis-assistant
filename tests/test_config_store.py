"""Regression tests: no settings writer may wipe config/api_keys.json."""
import json

from memory import config_manager as cm

SETTINGS = {"gemini_api_key": "AIza-real-key-1234567890", "assistant_name": "FRIDAY",
            "plugin_config": {"email": {"imap_password": "secret"}}}


def test_bom_prefixed_config_keeps_every_key(config_file):
    # Notepad saves UTF-8 with a BOM; json.loads(encoding="utf-8") rejects it.
    config_file.write_bytes(b"\xef\xbb\xbf" + json.dumps(SETTINGS).encode())
    cm.save_voice("Kore")
    saved = json.loads(config_file.read_text(encoding="utf-8-sig"))
    assert saved["gemini_api_key"] == SETTINGS["gemini_api_key"]
    assert saved["voice_name"] == "Kore"


def test_unreadable_config_is_kept_aside_not_overwritten(config_file):
    config_file.write_text(json.dumps(SETTINGS)[:-3])          # hand-edit typo / torn write
    cm.save_wake_word_enabled(True)
    backups = list(config_file.parent.glob("api_keys.corrupt-*.json"))
    assert len(backups) == 1 and "AIza-real-key" in backups[0].read_text()


def test_vision_camera_cache_keeps_other_settings(config_file):
    from actions import screen_processor
    config_file.write_text(json.dumps(SETTINGS))
    screen_processor._save_config_key("camera_index", 1)
    assert json.loads(config_file.read_text()) == {**SETTINGS, "camera_index": 1}
