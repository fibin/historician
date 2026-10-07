import json
import os
import threading
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer

import pytest

from historian import accounts, dotenv, history, main, web
from historian.publishers import threads as threads_pub

STORY = {"subject": "Тихо Браге", "topic": "лось", "threads_posts": ["Пост"], "sources": [], "engine": "codex"}


def test_dotenv_save_replaces_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nHISTORIAN_PUBLISH=false\nTHREADS_USER_ID=old\n", encoding="utf-8")
    dotenv.save({"THREADS_USER_ID": "new", "THREADS_ACCESS_TOKEN": "tok"}, str(env))
    assert env.read_text(encoding="utf-8").splitlines() == [
        "# comment", "HISTORIAN_PUBLISH=false", "THREADS_USER_ID=new", "THREADS_ACCESS_TOKEN=tok"]
    assert os.environ["THREADS_USER_ID"] == "new"


@pytest.fixture
def me(monkeypatch):
    who = {"tok": {"id": "42", "username": "hist"}, "tok2": {"id": "43", "username": "science"}}
    monkeypatch.setattr(threads_pub, "whoami", lambda t: who[t])


def test_save_token_fills_id_and_rejects_mismatch_and_duplicates(me):
    first = accounts.ensure()[0]
    a = web.save_token(first.id, "", "tok")
    assert (a["threads_user_id"], a["has_token"], a["threads_username"]) == ("42", True, "hist")
    assert "threads_token" not in a and accounts.get(first.id).threads_token == "tok"
    second = web.create_account("Наука")
    with pytest.raises(ValueError, match="ID 43"):
        web.save_token(second["id"], "7", "tok2")
    with pytest.raises(ValueError, match="уже подключён"):
        web.save_token(second["id"], "", "tok")
    assert web.save_token(second["id"], "", "tok2")["threads_username"] == "science"


def test_new_account_inherits_engine_and_language():
    first = accounts.ensure()[0]
    web.update_account(first.id, {"engine": "gemini", "language": "English"})
    a = web.create_account("Наука")
    assert (a["engine"], a["language"], a["auto_publish"]) == ("gemini", "English", False)
    with pytest.raises(ValueError):
        web.create_account("  ")


def test_update_account_validates(me):
    acc = accounts.ensure()[0]
    assert web.update_account(acc.id, {"post_time": "9:05", "theme": "  ", "name": "Наука "})["post_time"] == "09:05"
    saved = accounts.get(acc.id)
    assert saved.theme == "" and saved.name == "Наука"
    for bad in ({"post_time": "25:00"}, {"engine": "nope"}, {"name": ""}, {"auto_publish": True}):
        with pytest.raises(ValueError):
            web.update_account(acc.id, bad)
    web.save_token(acc.id, "", "tok")
    with pytest.raises(ValueError, match="о чём"):  # без темы автопубликация не включается
        web.update_account(acc.id, {"auto_publish": True})
    web.update_account(acc.id, {"theme": "космос"})
    assert web.update_account(acc.id, {"auto_publish": True})["auto_publish"] is True


def test_cannot_delete_last_account():
    acc = accounts.ensure()[0]
    with pytest.raises(ValueError):
        web.delete_account(acc.id)
    other = web.create_account("Второй")
    web.delete_account(other["id"])
    assert [a.id for a in accounts.list_all()] == [acc.id]


def test_state_falls_back_to_first_account_and_picks_up_scheduler_posts():
    acc = accounts.ensure()[0]
    s = web.state("nope")
    assert s["account"]["id"] == acc.id and [a["id"] for a in s["accounts"]] == [acc.id]
    assert s["job"]["story"] is None
    # планировщик сделал черновик и опубликовал, пока окно открыто
    main.save_draft(STORY, acc.out_dir)
    history.save(acc.history_path, history.add([], STORY, {"threads": "1"}))
    job = web.state(acc.id)["job"]
    assert job["story"]["subject"] == "Тихо Браге" and job["published"] is True


def test_published_post_shows_link_from_journal_or_threads(me, monkeypatch):
    acc = accounts.ensure()[0]
    web.save_token(acc.id, "", "tok")
    acc = accounts.get(acc.id)
    # опубликован в окне: ссылка сразу из журнала
    monkeypatch.setattr(threads_pub, "post_thread", lambda creds, parts, image_url=None: ["77"])
    main.save_draft(STORY, acc.out_dir)
    job = web.job_for(acc)
    web.do_publish(acc.id, job, ["Пост"])
    assert (job["published"], job["link"], job["link_kind"]) == (True, "https://www.threads.net/@x/post/77", "post")
    assert job["published_on"] == date.today().isoformat()
    # старая запись без ссылки: окно спрашивает ссылку у Threads, а если не вышло, ведёт на профиль
    monkeypatch.setattr(web, "_in_background", lambda fn, *args: fn(*args))
    old_entry = [{"date": "2026-10-07", "person": "Тихо Браге", "topic": "лось", "sources": [], "posted": {"threads": "5"}}]
    history.save(acc.history_path, old_entry)
    web.jobs.clear()
    job = web.job_for(acc)
    assert job["published"] and job["published_on"] == "2026-10-07"
    assert job["link"] == "https://www.threads.net/@x/post/5"
    monkeypatch.setattr(threads_pub, "permalink", lambda creds, post_id: None)
    web.jobs.clear()
    job = web.job_for(acc)
    assert (job["link"], job["link_kind"]) == ("https://www.threads.net/@hist", "profile")


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    web.Handler.page = "<html></html>"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _post(url, body, origin=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **({"Origin": origin} if origin else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_http_api(server):
    with urllib.request.urlopen(server + "/api/state") as r:
        first = json.load(r)["account"]["id"]
    code, acc = _post(server + "/api/accounts", {"name": "Science"})
    assert code == 200 and acc["id"] == "science"
    assert _post(server + "/api/account", {"id": "science", "post_time": "08:30"})[1]["post_time"] == "08:30"
    with urllib.request.urlopen(server + "/api/state?account=science") as r:
        s = json.load(r)
    assert s["account"]["id"] == "science" and len(s["accounts"]) == 2 and first != "science"
    assert _post(server + "/api/publish", {"id": "science", "posts": ["x"]})[0] == 400
    assert _post(server + "/api/account", {"id": "science", "name": "x"}, origin="https://evil.example")[0] == 403
    assert _post(server + "/api/account", {"id": "../main", "name": "x"})[0] == 400


def test_publish_uses_picked_image_and_rejects_unknown(me, monkeypatch):
    acc = accounts.ensure()[0]
    web.save_token(acc.id, "", "tok")
    acc = accounts.get(acc.id)
    assert web.update_account(acc.id, {"with_image": False})["with_image"] is False
    sent = {}
    monkeypatch.setattr(threads_pub, "post_thread", lambda creds, parts, image_url=None: sent.update(img=image_url) or ["8"])
    imgs = [{"url": f"https://u/{i}.jpg", "page": f"p{i}", "attribution": False} for i in range(2)]
    main.save_draft({**STORY, "images": imgs, "image": 0}, acc.out_dir)
    job = web.job_for(acc)
    web.do_publish(acc.id, job, ["Пост"], 1)
    assert sent["img"] == "https://u/1.jpg" and acc.history()[-1]["posted"]["image"] == "p1"


def test_http_publish_checks_image_index(server, me):
    acc = accounts.ensure()[0]
    web.save_token(acc.id, "", "tok")
    main.save_draft({**STORY, "images": [{"url": "u", "page": "p"}], "image": 0}, accounts.get(acc.id).out_dir)
    code, body = _post(server + "/api/publish", {"id": acc.id, "posts": ["x"], "image": 5})
    assert code == 400 and "картинки" in body["error"]
