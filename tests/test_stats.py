from datetime import date, datetime

from historian import accounts, history, stats
from historian.publishers import threads as threads_pub

STORY = {"subject": "Тихо Браге", "topic": "лось", "threads_posts": ["Лось Тихо Браге напился пива."], "sources": []}


def _account():
    acc = accounts.ensure()[0]
    accounts.set_token(acc, "42", "tok", "hist")
    acc.save()
    return acc


def test_refresh_saves_post_stats_and_followers(monkeypatch):
    acc = _account()
    entries = history.add([], STORY, {"threads": "100"})
    assert entries[0]["hook"] == "Лось Тихо Браге напился пива."
    history.save(acc.history_path, entries)
    monkeypatch.setattr(threads_pub, "followers", lambda creds: 57)
    monkeypatch.setattr(threads_pub, "post_insights", lambda creds, pid: {"views": 900, "likes": 12, "replies": 3})
    now = datetime(2026, 10, 7, 12, 0)

    data = stats.refresh(acc, now)
    assert data["followers"] == 57 and data["error"] == ""
    assert acc.history()[0]["stats"] == {"views": 900, "likes": 12, "replies": 3}

    monkeypatch.setattr(threads_pub, "followers", lambda creds: 1 / 0)
    stats.refresh(acc, datetime(2026, 10, 7, 15, 0))  # три часа спустя: не трогаем API
    assert not stats.load(acc)["error"]
    summary = stats.summary(acc)
    assert summary["followers"] == 57 and summary["posts"][0]["stats"]["views"] == 900


def test_missing_permission_is_explained(monkeypatch):
    acc = _account()

    def no(creds):
        raise threads_pub.NoPermission("nope")
    monkeypatch.setattr(threads_pub, "followers", no)
    assert "threads_manage_insights" in stats.refresh(acc, force=True)["error"]


def test_followers_change_over_a_week():
    log = [{"date": "2026-09-29", "n": 10}, {"date": "2026-09-30", "n": 12}, {"date": "2026-10-07", "n": 30}]
    assert stats.followers_change({"followers_log": log}, today=date(2026, 10, 7)) == 18
    assert stats.followers_change({"followers_log": log[2:]}, today=date(2026, 10, 7)) is None


def test_feedback_lists_best_and_worst_settled_posts():
    def entry(subject, views, day="2026-10-01"):
        return {"date": day, "subject": subject, "topic": "t", "hook": f"Начало {subject}", "stats": {"views": views}}
    entries = [entry("A", 100), entry("B", 5000), entry("C", 50), entry("D", 800)]
    assert stats.feedback_for_prompt(entries[:3], today=date(2026, 10, 7)) == ""  # мало постов
    text = stats.feedback_for_prompt(entries + [entry("E", 99999, day="2026-10-07")], today=date(2026, 10, 7))
    best, worst = text.split("Зашли хуже всего:")
    assert "B:" in best and "D:" in best and "C:" in worst and "A:" in worst
    assert "E:" not in text  # вчерашний пост ещё набирает просмотры
    assert "«Начало B»" in best


def test_feedback_reaches_the_prompt(monkeypatch):
    from historian import engines, main
    seen = {}

    def fake(engine, summary, theme, language, feedback=""):
        seen["feedback"] = feedback
        return {"subject": "X", "topic": "t", "threads_posts": ["p"], "sources": [], "engine": engine}
    monkeypatch.setattr(engines, "generate_story", fake)
    entries = [{"date": "2026-01-01", "subject": s, "topic": "t", "stats": {"views": v}}
               for s, v in [("A", 1), ("B", 2), ("C", 3), ("D", 4)]]
    main.generate("claude-code", entries, "тема")
    assert "Зашли лучше всего" in seen["feedback"]
    assert "Зашли лучше всего" in engines._user_prompt("-", seen["feedback"])


class _Resp:
    def __init__(self, code, body):
        self.status_code, self._body, self.text = code, body, str(body)

    def json(self):
        return self._body


def test_insights_parse_api_shapes(monkeypatch):
    from historian.config import ThreadsCredentials
    monkeypatch.undo()  # настоящие функции, подменяем только сеть
    creds = ThreadsCredentials("42", "tok")
    replies = {
        "/100/insights": _Resp(200, {"data": [{"name": "views", "period": "lifetime", "values": [{"value": 321}]},
                                              {"name": "likes", "period": "lifetime", "values": [{"value": 9}]}]}),
        "/42/threads_insights": _Resp(200, {"data": [{"name": "followers_count", "total_value": {"value": 77}}]}),
    }
    monkeypatch.setattr(threads_pub.requests, "get", lambda url, params, timeout: replies[url[len(threads_pub.BASE):]])
    assert threads_pub.post_insights(creds, "100") == {"views": 321, "likes": 9}
    assert threads_pub.followers(creds) == 77

    denied = _Resp(403, {"error": {"message": "Application does not have permission for this action", "code": 10}})
    monkeypatch.setattr(threads_pub.requests, "get", lambda url, params, timeout: denied)
    try:
        threads_pub.followers(creds)
        raise AssertionError("expected NoPermission")
    except threads_pub.NoPermission:
        pass
