from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "gui" / "copilot_app.py")


def test_gui_without_env_file_shows_setup_instructions(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_ENV", str(tmp_path / "missing.env"))
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("copilot.env fehlt" in e.value for e in at.error)
