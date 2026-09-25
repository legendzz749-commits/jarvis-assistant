"""Regression tests: a damaged or interrupted memory write must never wipe stored facts."""
import json

import pytest

from memory import memory_manager as mm


@pytest.fixture
def mem_path(tmp_path, monkeypatch):
    path = tmp_path / "long_term.json"
    monkeypatch.setattr(mm, "MEMORY_PATH", path)
    return path


FACTS = {"identity": {"name": {"value": "Tony", "updated": "2026-01-01"}},
         "relationships": {"ayse_sister": {"value": "Ayşe is my sister", "updated": "2026-01-02"}}}


def test_unreadable_file_is_kept_not_overwritten(mem_path):
    # truncated write / hand-edit typo
    mem_path.write_text(json.dumps(FACTS, ensure_ascii=False)[:-5], encoding="utf-8")

    memory = mm.load_memory()
    memory["preferences"]["coffee"] = {"value": "black", "updated": "2026-02-01"}
    mm.save_memory(memory)

    backups = list(mem_path.parent.glob("long_term.corrupt-*.json"))
    assert len(backups) == 1
    assert "Ayşe is my sister" in backups[0].read_text(encoding="utf-8")
    assert "coffee" in json.loads(mem_path.read_text(encoding="utf-8"))["preferences"]


def test_failed_write_leaves_previous_store_intact(mem_path, monkeypatch):
    mm.save_memory(json.loads(json.dumps(FACTS)))

    def disk_full(*_a, **_k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(mm.os, "replace", disk_full)
    with pytest.raises(OSError):
        mm.save_memory({**FACTS, "notes": {"x": {"value": "y"}}})

    assert json.loads(mem_path.read_text(encoding="utf-8"))["relationships"] == FACTS["relationships"]


def test_session_summary_round_trip(mem_path):
    mm.save_memory(json.loads(json.dumps(FACTS)))
    mm.save_session_summary("Talked about the roadmap.")
    assert mm.pop_last_session()["summary"] == "Talked about the roadmap."
    assert mm.pop_last_session() is None
    assert mm.load_memory()["identity"] == FACTS["identity"]


def test_a_fact_named_value_does_not_replace_its_category(mem_path):
    mm.save_memory(json.loads(json.dumps(FACTS)))
    mm.update_memory({"relationships": {"value": {"value": "a key literally named value"}}})
    rel = mm.load_memory()["relationships"]
    assert "ayse_sister" in rel and "value" in rel


def test_concurrent_writers_do_not_lose_updates(mem_path):
    import threading
    mm.save_memory(mm._empty_memory())
    threads = [threading.Thread(target=mm.update_memory,
                                args=({"notes": {f"n{i}": {"value": str(i)}}},))
               for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(mm.load_memory()["notes"]) == 20


def test_a_non_dict_category_does_not_break_the_prompt(mem_path):
    mem_path.write_text(json.dumps({"identity": {"name": {"value": "Tony"}},
                                    "preferences": ["coffee", "tea"]}), encoding="utf-8")
    memory = mm.load_memory()
    assert memory["preferences"] == {} and memory["_preferences_unreadable"] == ["coffee", "tea"]
    mm.format_memory_for_prompt(memory)
