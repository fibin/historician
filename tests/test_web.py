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
    assert s == {"user_id": "42", "has_token": True, "username": "hist"}
    assert "THREADS_USER_ID=42" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_save_settings_rejects_mismatched_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(threads_pub, "whoami", lambda t: {"id": "42", "username": "hist"})
    with pytest.raises(ValueError):
        web.save_settings("7", "tok")
