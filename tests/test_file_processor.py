"""Regression tests: files handed to Gemini must arrive as real Parts; CSV/TSV must parse."""
import io
from types import SimpleNamespace

import pytest
from google.genai import types

from actions import file_processor as fp
from core import gemini


@pytest.fixture
def sent(monkeypatch):
    calls = []
    monkeypatch.setattr(fp.gemini, "call",
                        lambda contents, **k: calls.append(contents) or SimpleNamespace(text="ok"))
    return calls


def _media_parts(contents):
    return [p for p in gemini._to_live_parts(contents) if "inline_data" in p]


def test_image_reaches_the_model(tmp_path, sent):
    from PIL import Image
    path = tmp_path / "receipt.png"
    Image.new("RGB", (4, 4), "white").save(path)

    fp._process_image(path, "ocr", {"save": False})

    (contents,) = sent
    assert all(isinstance(c, (str, types.Part)) for c in contents)
    assert [p["inline_data"]["mime_type"] for p in _media_parts(contents)] == ["image/png"]


def test_audio_is_sent_as_a_valid_part(tmp_path, sent):
    path = tmp_path / "memo.mp3"
    path.write_bytes(b"ID3fake")

    fp._process_audio(path, "transcribe", {"save": False})

    (contents,) = sent
    assert all(isinstance(c, (str, types.Part)) for c in contents)
    assert [p["inline_data"]["mime_type"] for p in _media_parts(contents)] == ["audio/mpeg"]


@pytest.mark.parametrize("name,body", [("sales.csv", "city,total\nIzmir,3\nBursa,5\n"),
                                       ("sales.tsv", "city\ttotal\nIzmir\t3\nBursa\t5\n")])
def test_csv_and_tsv_parse_into_columns(tmp_path, name, body):
    pytest.importorskip("pandas")
    path = tmp_path / name
    path.write_text(body)

    out = fp._process_data(path, "csv", "info", {})

    assert "Could not read" not in out
    assert "total" in out and "2" in out
