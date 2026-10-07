import json

import pytest

from historian import history, main, research, writer
from historian.publishers import threads as threads_pub
from historian.publishers import x as x_pub

STORY = {
    "person": "Тихо Браге",
    "topic": "лось, который напился пива",
    "x_posts": ["Крючок.", "Середина. " * 40, "Источник: https://example.com/a"],
    "threads_posts": ["Вся история.", "https://example.com/a"],
    "sources": ["https://example.com/a", "https://example.com/b"],
}


@pytest.fixture
def fake_llm(monkeypatch):
    calls = []

    def find_story(client, summary):
        calls.append(summary)
        return "ДОСЬЕ", [{"url": "https://example.com/a", "title": "A"}]

    stories = iter([dict(STORY, person="Пётр I"), dict(STORY)])
    monkeypatch.setattr(research, "find_story", find_story)
    monkeypatch.setattr(writer, "write_posts", lambda c, d, u: next(stories))
    return calls


def test_generate_skips_recent_people_and_fits_lengths(fake_llm):
    entries = [{"person": "Пётр I", "topic": "x", "sources": []}]
    story = main.generate(None, entries)
    assert story["person"] == "Тихо Браге"
    assert len(fake_llm) == 2 and "Пётр I" in fake_llm[0]
    assert all(len(p) <= 280 for p in story["x_posts"])
    assert len(story["x_posts"]) > 3  # длинная середина разрезана


def test_draft_mode_does_not_publish(fake_llm, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "HISTORY_PATH", str(tmp_path / "h.json"))
    monkeypatch.setattr(main, "publish", lambda *a, **k: pytest.fail("published in draft mode"))
    monkeypatch.setattr("anthropic.Anthropic", lambda: None)
    main.main(["--out-dir", str(tmp_path / "out")])
    drafts = list((tmp_path / "out").glob("*.json"))
    assert len(drafts) == 1
    assert not (tmp_path / "h.json").exists()


def test_publish_from_draft_records_history(tmp_path, monkeypatch):
    draft = tmp_path / "d.json"
    draft.write_text(json.dumps(STORY, ensure_ascii=False), encoding="utf-8")
    hist = tmp_path / "h.json"
    monkeypatch.setattr(main, "HISTORY_PATH", str(hist))
    for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET",
              "THREADS_USER_ID", "THREADS_ACCESS_TOKEN"):
        monkeypatch.setenv(k, "v")
    sent = {}
    monkeypatch.setattr(x_pub, "post_thread", lambda c, p: sent.setdefault("x", p) and ["111", "112"])
    monkeypatch.setattr(threads_pub, "post_thread", lambda c, p: sent.setdefault("t", p) and ["222"])
    main.main(["--from-draft", str(draft), "--publish"])
    saved = history.load(str(hist))
    assert saved[0]["person"] == "Тихо Браге"
    assert saved[0]["posted"] == {"x": "https://x.com/i/status/111", "threads": "222"}


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, json.dumps(data)

    def json(self):
        return self._data


def test_x_thread_chains_replies(monkeypatch):
    payloads = []

    class FakeSession:
        def __init__(self, *a):
            pass

        def post(self, url, json, timeout):
            payloads.append(json)
            return FakeResp(201, {"data": {"id": str(len(payloads))}})

    monkeypatch.setattr(x_pub, "OAuth1Session", FakeSession)
    creds = x_pub.XCredentials("k", "s", "t", "ts")
    ids = x_pub.post_thread(creds, ["a", "b", "c"])
    assert ids == ["1", "2", "3"]
    assert "reply" not in payloads[0]
    assert payloads[2]["reply"] == {"in_reply_to_tweet_id": "2"}


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
    assert len(main.fit_story(dict(STORY))["x_posts"]) > 3
