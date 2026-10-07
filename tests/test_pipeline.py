import json

import pytest

from historian import history, main, research, writer
from historian.publishers import threads as threads_pub

STORY = {
    "person": "Тихо Браге",
    "topic": "лось, который напился пива",
    "threads_posts": ["Крючок.", "Середина. " * 80, "Источник: https://example.com/a"],
    "sources": ["https://example.com/a", "https://example.com/b"],
}


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def find_story(client, summary):
        calls.append(summary)
        return "ДОСЬЕ", [{"url": "https://example.com/a", "title": "A"}]

    stories = iter([dict(STORY, person="Пётр I"), dict(STORY)])
    monkeypatch.setattr("anthropic.Anthropic", lambda: None)
    monkeypatch.setattr(research, "find_story", find_story)
    monkeypatch.setattr(writer, "write_posts", lambda c, d, u: next(stories))
    return calls


def test_generate_skips_recent_people_and_fits_lengths(fake_llm):
    entries = [{"person": "Пётр I", "topic": "x", "sources": []}]
    story = main.generate("api", entries)
    assert story["person"] == "Тихо Браге"
    assert len(fake_llm) == 2 and "Пётр I" in fake_llm[0]
    assert all(len(p) <= 500 for p in story["threads_posts"])
    assert len(story["threads_posts"]) > 3  # длинная середина разрезана


def test_draft_mode_does_not_publish(fake_llm, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "HISTORY_PATH", str(tmp_path / "h.json"))
    monkeypatch.setattr(main, "publish", lambda *a, **k: pytest.fail("published in draft mode"))
    monkeypatch.setattr("anthropic.Anthropic", lambda: None)
    main.main(["--engine", "api", "--out-dir", str(tmp_path / "out")])
    drafts = list((tmp_path / "out").glob("*.json"))
    assert len(drafts) == 1
    assert not (tmp_path / "h.json").exists()


def test_publish_from_draft_records_history(tmp_path, monkeypatch):
    draft = tmp_path / "d.json"
    draft.write_text(json.dumps(STORY, ensure_ascii=False), encoding="utf-8")
    hist = tmp_path / "h.json"
    monkeypatch.setattr(main, "HISTORY_PATH", str(hist))
    for k in ("THREADS_USER_ID", "THREADS_ACCESS_TOKEN"):
        monkeypatch.setenv(k, "v")
    sent = {}
    monkeypatch.setattr(threads_pub, "post_thread", lambda c, p: sent.setdefault("t", p) and ["222"])
    main.main(["--from-draft", str(draft), "--publish"])
    saved = history.load(str(hist))
    assert saved[0]["person"] == "Тихо Браге"
    assert saved[0]["posted"] == {"threads": "222"}


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, json.dumps(data)

    def json(self):
        return self._data


def test_threads_container_then_publish(monkeypatch):
    calls = []

    def fake_post(url, params, timeout):
        calls.append((url.rsplit("/", 1)[-1], dict(params)))
        return FakeResp(200, {"id": f"id{len(calls)}"})

    monkeypatch.setattr(threads_pub.requests, "post", fake_post)
    monkeypatch.setattr(threads_pub.time, "sleep", lambda s: None)
    creds = threads_pub.ThreadsCredentials("u1", "tok")
    ids = threads_pub.post_thread(creds, ["one", "two"])
    assert [c[0] for c in calls] == ["threads", "threads_publish", "threads", "threads_publish"]
    assert calls[2][1]["reply_to_id"] == ids[0]
    assert calls[1][1]["creation_id"] == "id1"


def test_from_draft_rejects_recent_person_and_fits(tmp_path, monkeypatch):
    draft = tmp_path / "d.json"
    draft.write_text(json.dumps(STORY, ensure_ascii=False), encoding="utf-8")
    hist = tmp_path / "h.json"
    history.save(str(hist), [{"person": "Тихо Браге", "topic": "t", "sources": []}])
    monkeypatch.setattr(main, "HISTORY_PATH", str(hist))
    with pytest.raises(SystemExit):
        main.main(["--from-draft", str(draft)])
    assert len(main.fit_story(dict(STORY))["threads_posts"]) > 3


def test_claude_code_engine_reads_structured_output(monkeypatch):
    from historian import claude_code

    seen = {}

    class Proc:
        returncode = 0
        stderr = ""
        stdout = json.dumps({"is_error": False, "structured_output": dict(STORY, dossier="Д")})

    def fake_run(cmd, input, **kw):
        seen["cmd"], seen["input"] = cmd, input
        return Proc()

    monkeypatch.setattr(claude_code.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
    story = claude_code.generate_story("- Пётр I: x")
    assert story["dossier"] == "Д"
    assert "--json-schema" in seen["cmd"] and "WebSearch,WebFetch" in seen["cmd"]
    assert "Пётр I" in seen["input"]
