import json

import pytest

from historian import accounts, history, main, research, writer
from historian.publishers import threads as threads_pub

STORY = {
    "subject": "Тихо Браге",
    "topic": "лось, который напился пива",
    "threads_posts": ["Крючок.", "Середина. " * 80, "Источник: https://example.com/a"],
    "sources": ["https://example.com/a", "https://example.com/b"],
}


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def find_story(client, summary, theme):
        calls.append((summary, theme))
        return "ДОСЬЕ", [{"url": "https://example.com/a", "title": "A"}]

    def write_posts(client, dossier, urls, theme, language):
        calls.append((theme, language))
        return next(stories)

    stories = iter([dict(STORY, subject="Пётр I"), dict(STORY)])
    monkeypatch.setattr("anthropic.Anthropic", lambda: None)
    monkeypatch.setattr(research, "find_story", find_story)
    monkeypatch.setattr(writer, "write_posts", write_posts)
    return calls


def test_generate_skips_recent_people_and_fits_lengths(fake_llm):
    entries = [{"person": "Пётр I", "topic": "x", "sources": []}]  # запись старого формата
    story = main.generate("api", entries, theme="наука", language="English")
    assert story["subject"] == "Тихо Браге"
    assert len(fake_llm) == 4 and "Пётр I" in fake_llm[0][0]
    assert fake_llm[0][1] == "наука" and fake_llm[1] == ("наука", "English")
    assert all(len(p) <= 500 for p in story["threads_posts"])
    assert len(story["threads_posts"]) > 3  # длинная середина разрезана


def test_generate_needs_a_theme():
    with pytest.raises(SystemExit, match="о чём"):
        main.generate("claude-code", [], theme="  ")


def test_draft_mode_does_not_publish(fake_llm, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "publish", lambda *a, **k: pytest.fail("published in draft mode"))
    main.main(["--engine", "api"])
    drafts = list((tmp_path / "accounts" / "main" / "out").glob("*.json"))
    assert len(drafts) == 1
    assert not (tmp_path / "accounts" / "main" / "history.json").exists()


def test_publish_from_draft_records_history(tmp_path, monkeypatch):
    draft = tmp_path / "d.json"
    old_format = {("person" if k == "subject" else k): v for k, v in STORY.items()}  # черновик прошлой версии
    draft.write_text(json.dumps(old_format, ensure_ascii=False), encoding="utf-8")
    for k in ("THREADS_USER_ID", "THREADS_ACCESS_TOKEN"):
        monkeypatch.setenv(k, "v")  # из старого .env создаётся первый аккаунт
    sent = {}
    monkeypatch.setattr(threads_pub, "post_thread", lambda c, p: sent.setdefault("t", p) and ["222"])
    main.main(["--from-draft", str(draft), "--publish"])
    saved = history.load(str(tmp_path / "accounts" / "main" / "history.json"))
    assert saved[0]["subject"] == "Тихо Браге"
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
    acc = accounts.create("Наука")
    history.save(acc.history_path, [{"person": "Тихо Браге", "topic": "t", "sources": []}])
    with pytest.raises(SystemExit):
        main.main(["--from-draft", str(draft), "--account", acc.id])
    assert len(main.fit_story(dict(STORY))["threads_posts"]) > 3
