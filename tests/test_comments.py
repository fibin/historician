import pytest

from historian import accounts, comments, engines, history, web
from historian.publishers import threads as threads_pub

REAL_CONVERSATION = threads_pub.conversation  # conftest подменяет его заглушкой


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, str(body)

    def json(self):
        return self._body

STORY = {"subject": "Тихо Браге", "topic": "лось", "threads_posts": ["Лось напився пива."], "sources": ["https://s"]}


@pytest.fixture
def acc(monkeypatch):
    a = accounts.ensure()[0]
    accounts.set_token(a, "42", "tok", "istoriia")
    a.save()
    history.save(a.history_path, history.add([], STORY, {"threads": "100", "link": "https://t/100"}))
    convo = [
        {"id": "101", "username": "istoriia", "text": "Продовження ланцюжка", "replied_to": {"id": "100"}},
        {"id": "200", "username": "olena", "text": "А звідки відомо про пиво?", "replied_to": {"id": "100"}},
        {"id": "201", "username": "petro", "text": "👍", "replied_to": {"id": "100"}},
        {"id": "202", "username": "ivan", "text": "Вже відповіли", "replied_to": {"id": "100"}},
        {"id": "203", "username": "istoriia", "text": "Так!", "replied_to": {"id": "202"}},
        {"id": "204", "username": "spam", "text": "Сховано", "hide_status": "HIDDEN"},
    ]
    monkeypatch.setattr(threads_pub, "conversation", lambda creds, post_id, pages=5: convo)
    return a


def test_check_finds_unanswered_and_drafts_replies(acc, monkeypatch):
    seen = {}

    def ask(engine, system, user, schema, search=False, timeout=900):
        seen.update(system=system, user=user)
        return {"replies": [{"id": "200", "reply": "З листів сучасників."}, {"id": "201", "reply": ""}]}
    monkeypatch.setattr(engines, "ask", ask)
    data = comments.check(acc)
    assert data["error"] == ""
    items = {c["id"]: c for c in comments.pending(acc)["items"]}
    assert set(items) == {"200", "201"}  # свои, отвеченные и скрытые не показываем
    assert items["200"]["draft"] == "З листів сучасників." and items["200"]["link"] == "https://t/100"
    assert items["201"]["suggest_skip"]
    assert "[200] @olena: А звідки відомо про пиво?" in seen["user"] and "Начало: Лось напився пива." in seen["user"]
    # повторная проверка не дублирует и не зовёт ИИ, если нового нет
    monkeypatch.setattr(engines, "ask", lambda *a, **k: pytest.fail("no new comments"))
    comments.check(acc)
    assert len(comments.load(acc)["items"]) == 2
    # на комментарий ответили с телефона: из списка он уходит
    threads_pub.conversation(None, "100").append({"id": "205", "username": "istoriia", "replied_to": {"id": "200"}})
    comments.check(acc)
    assert [c["id"] for c in comments.pending(acc)["items"]] == ["201"]


def test_send_and_skip(acc, monkeypatch):
    monkeypatch.setattr(engines, "ask", lambda *a, **k: {"replies": []})
    comments.check(acc)
    sent = {}
    monkeypatch.setattr(threads_pub, "reply", lambda creds, cid, text: sent.update(cid=cid, text=text) or "900")
    with pytest.raises(ValueError, match="Напишите"):
        comments.send(acc, "200", "  ")
    item = comments.send(acc, "200", " Дякую! ")
    assert sent == {"cid": "200", "text": "Дякую!"} and item["status"] == "answered"
    with pytest.raises(ValueError, match="уже ответили"):
        comments.send(acc, "200", "ще раз")
    comments.skip(acc, "201")
    assert comments.pending(acc)["items"] == []


def test_missing_permission_is_explained(acc, monkeypatch):
    def denied(creds, post_id, pages=5):
        raise threads_pub.NoPermission("no")
    monkeypatch.setattr(threads_pub, "conversation", denied)
    assert "threads_read_replies" in comments.check(acc)["error"]


def test_conversation_follows_paging(monkeypatch):
    from historian.config import ThreadsCredentials
    pages = {None: _Resp(200, {"data": [{"id": "1"}], "paging": {"next": "https://next"}}),
             "https://next": _Resp(200, {"data": [{"id": "2"}]})}
    monkeypatch.setattr(threads_pub, "conversation", REAL_CONVERSATION)
    monkeypatch.setattr(threads_pub.requests, "get",
                        lambda url, params, timeout: pages[None if url.endswith("/conversation") else url])
    assert [r["id"] for r in threads_pub.conversation(ThreadsCredentials("42", "t"), "100")] == ["1", "2"]


def test_state_shows_pending_comments(acc, monkeypatch):
    monkeypatch.setattr(engines, "ask", lambda *a, **k: {"replies": []})
    comments.check(acc)
    s = web.state(acc.id)
    assert {c["id"] for c in s["comments"]["items"]} == {"200", "201"}
