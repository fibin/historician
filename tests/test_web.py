import os

import pytest

from historian import dotenv, web
from historian.publishers import threads as threads_pub


def test_dotenv_save_replaces_and_appends(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nHISTORIAN_PUBLISH=false\nTHREADS_USER_ID=old\n", encoding="utf-8")
    for k in ("THREADS_USER_ID", "THREADS_ACCESS_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    dotenv.save({"THREADS_USER_ID": "new", "THREADS_ACCESS_TOKEN": "tok"}, str(env))
    assert env.read_text(encoding="utf-8").splitlines() == [
        "# comment", "HISTORIAN_PUBLISH=false", "THREADS_USER_ID=new", "THREADS_ACCESS_TOKEN=tok"]
    assert os.environ["THREADS_USER_ID"] == "new"


def test_save_settings_fills_id_from_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k in ("THREADS_USER_ID", "THREADS_ACCESS_TOKEN", "THREADS_USERNAME"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(threads_pub, "whoami", lambda t: {"id": "42", "username": "hist"})
    s = web.save_settings("", "tok")
    assert (s["user_id"], s["has_token"], s["username"]) == ("42", True, "hist")
    assert "THREADS_USER_ID=42" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_save_settings_rejects_mismatched_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(threads_pub, "whoami", lambda t: {"id": "42", "username": "hist"})
    with pytest.raises(ValueError):
        web.save_settings("7", "tok")


def test_set_engine_saves_choice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HISTORIAN_ENGINE", raising=False)
    s = web.set_engine("codex")
    assert s["engine"] == "codex" and {e["id"] for e in s["engines"]} == {"claude-code", "codex", "gemini", "api"}
    assert "HISTORIAN_ENGINE=codex" in (tmp_path / ".env").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        web.set_engine("nope")
