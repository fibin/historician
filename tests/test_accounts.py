import glob
import json
from datetime import date, datetime

import pytest

from historian import accounts, history, main
from historian.publishers import threads as threads_pub

STORY = {"subject": "Тихо Браге", "topic": "лось", "threads_posts": ["Пост"], "sources": []}


def test_migrates_old_settings_once(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "history.json").write_text(
        json.dumps([{"date": "2026-10-07", "person": "Франклин", "topic": "t", "sources": []}]), encoding="utf-8")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "2026-10-07.json").write_text(json.dumps(STORY), encoding="utf-8")
    monkeypatch.setenv("THREADS_USER_ID", "42")
    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("THREADS_USERNAME", "hist")
    monkeypatch.setenv("HISTORIAN_ENGINE", "codex")
    monkeypatch.setenv("HISTORIAN_PUBLISH", "true")

    [acc] = accounts.ensure()
    assert (acc.id, acc.engine, acc.auto_publish, acc.threads_username) == ("main", "codex", True, "hist")
    assert acc.creds().user_id == "42" and acc.language == "українська"
    assert acc.theme == accounts.HISTORY_THEME  # перенесённый аккаунт пишет, как раньше
    assert history.subject_of(acc.history()[0]) == "Франклин"
    assert (tmp_path / "accounts" / "main" / "out" / "2026-10-07.json").exists()
    assert (tmp_path / "data" / "history.json").exists()  # старые файлы на месте

    monkeypatch.setenv("THREADS_ACCESS_TOKEN", "other")
    assert [a.threads_token for a in accounts.ensure()] == ["tok"]  # второй раз не переносит


def test_old_default_theme_becomes_detailed_history_theme():
    acc = accounts.create("A", theme=accounts._OLD_DEFAULT_THEME)
    assert accounts.get(acc.id).theme == accounts.HISTORY_THEME
    assert accounts.create("B").theme == ""


def test_create_list_get_delete():
    a = accounts.create("Science!")
    b = accounts.create("Science")
    c = accounts.create("Морські пригоди")
    assert accounts.create("???").id == "account"
    assert [x.id for x in accounts.list_all()][:3] == ["science", "science-2", "morski-pryhody"]
    assert accounts.get("science-2").name == "Science"
    for bad in ("../science", "", "nope"):
        with pytest.raises(ValueError):
            accounts.get(bad)
    accounts.delete(b.id)
    assert [x.id for x in accounts.list_all()] == [a.id, c.id, "account"]
    assert accounts.create("Science").id == "science-2"  # удалённый лежит в _deleted и не мешает


def test_token_refresh_weekly_and_once_a_day_on_failure(monkeypatch):
    acc = accounts.create("A")
    accounts.set_token(acc, "1", "old", "a", today=date(2026, 10, 1))
    acc.save()
    calls = []

    def refresh(token):
        calls.append(token)
        if len(calls) == 1:
            raise RuntimeError("сеть")
        return {"access_token": "new", "expires_in": 60 * 86400}

    monkeypatch.setattr(threads_pub, "refresh_token", refresh)
    assert not accounts.refresh_token_if_needed(acc, date(2026, 10, 5))   # меньше недели
    assert not accounts.refresh_token_if_needed(acc, date(2026, 10, 8))   # ошибка
    assert not accounts.refresh_token_if_needed(acc, date(2026, 10, 8))   # сегодня уже пробовали
    assert accounts.refresh_token_if_needed(acc, date(2026, 10, 9))
    saved = accounts.get(acc.id)
    assert (saved.threads_token, saved.token_date, saved.token_expires) == ("new", "2026-10-09", "2026-12-08")
    assert calls == ["old", "old"]


@pytest.fixture
def scheduled(monkeypatch):
    """Два аккаунта: один публикует сам в 10:00, второй только вручную."""
    auto = accounts.create("Auto", auto_publish=True, post_time="10:00", theme="море", language="English")
    accounts.set_token(auto, "1", "t1", "auto")
    auto.save()
    manual = accounts.create("Manual")
    accounts.set_token(manual, "2", "t2", "manual")
    manual.save()
    log = {"generated": [], "posted": []}

    def generate(engine, entries, theme, language):
        log["generated"].append((engine, theme, language))
        if log.get("fail"):
            raise RuntimeError("лимит подписки")
        return dict(STORY)

    monkeypatch.setattr(main, "generate", generate)
    monkeypatch.setattr(threads_pub, "post_thread", lambda creds, parts: log["posted"].append(creds.user_id) or ["99"])
    monkeypatch.setattr(threads_pub, "refresh_token", lambda t: pytest.fail("токен свежий"))
    return auto, log


def test_due_publishes_once_a_day_after_post_time(scheduled):
    auto, log = scheduled
    main.run_due(datetime(2026, 10, 7, 9, 0))
    assert log["posted"] == []
    main.run_due(datetime(2026, 10, 7, 15, 0))  # компьютер включили только днём
    assert log["posted"] == ["1"] and log["generated"] == [("claude-code", "море", "English")]
    entry = history.load(auto.history_path)[0]
    assert entry["date"] == date.today().isoformat() and entry["posted"] == {"threads": "99"}
    assert len(glob.glob(auto.out_dir + "/*.json")) == 1


def test_due_skips_day_already_posted_manually(scheduled):
    auto, log = scheduled
    today = datetime.now().replace(hour=23, minute=0)
    history.save(auto.history_path, history.add([], STORY, {"threads": "5"}))
    main.run_due(today)
    assert log["generated"] == []


def test_due_gives_up_after_two_failures(scheduled):
    auto, log = scheduled
    log["fail"] = True
    for hour in (10, 11, 12):
        main.run_due(datetime(2026, 10, 7, hour, 0))
    assert len(log["generated"]) == 2 and log["posted"] == []
    assert accounts.attempts_today(auto, date(2026, 10, 7)) == 2
    assert accounts.attempts_today(auto, date(2026, 10, 8)) == 0
