"""Окно бота в браузере: аккаунты Threads, у каждого свои настройки, черновик и публикация.

Запуск: двойной клик по Historian.bat или `python -m historian.web`.
Сервер слушает только 127.0.0.1, страница открывается в браузере сама.
"""
import glob
import json
import os
import re
import subprocess
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import accounts, engines, main
from .config import LANGUAGE, THREADS_LIMIT
from .publishers import threads as threads_pub

PORT = int(os.environ.get("HISTORIAN_PORT", "8765"))
PAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page.html")
TASK_NAME = "Historian bot"
BUSY = ("generating", "publishing")

_lock = threading.Lock()
jobs: dict[str, dict] = {}  # по id аккаунта: что сейчас происходит и какой черновик открыт
schedule = {"supported": os.name == "nt", "status": "unknown"}


def _is_published(acc: accounts.Account, story: dict) -> bool:
    return any(e["person"] == story.get("person") and e["topic"] == story.get("topic")
               for e in acc.history())


def _latest_draft(acc: accounts.Account) -> str | None:
    drafts = sorted(glob.glob(os.path.join(acc.out_dir, "*.json")))
    return drafts[-1] if drafts else None


def job_for(acc: accounts.Account) -> dict:
    """Состояние аккаунта в окне. Если планировщик успел сделать новый черновик или пост, подхватываем их."""
    with _lock:
        job = jobs.setdefault(acc.id, {"status": "idle", "message": "", "started": None, "story": None,
                                       "draft": None, "published": False, "link": None})
        if job["status"] in BUSY:
            return job
        latest = _latest_draft(acc)
        if latest and latest != job["draft"]:
            with open(latest, encoding="utf-8") as f:
                job.update(story=json.load(f), draft=latest, link=None)
        if job["story"]:
            job["published"] = _is_published(acc, job["story"])
        return job


def engines_info() -> list[dict]:
    return [{"id": k, "label": v["label"], "setup": v["setup"], "available": engines.available(k)}
            for k, v in engines.ENGINES.items()]


def state(account_id: str | None) -> dict:
    all_accounts = accounts.ensure()
    acc = next((a for a in all_accounts if a.id == account_id), all_accounts[0])
    job = job_for(acc)
    summary = [{"id": a.id, "name": a.name, "username": a.threads_username, "has_token": bool(a.threads_token),
                "auto_publish": a.auto_publish, "post_time": a.post_time,
                "busy": jobs.get(a.id, {}).get("status") in BUSY} for a in all_accounts]
    elapsed = int(time.time() - job["started"]) if job["status"] in BUSY else 0
    return {"accounts": summary, "account": acc.public(), "job": {**job, "elapsed": elapsed},
            "engines": engines_info(), "schedule": schedule, "limit": THREADS_LIMIT,
            "default_theme": accounts.DEFAULT_THEME}


def create_account(name: str) -> dict:
    if not name.strip():
        raise ValueError("Введите название аккаунта")
    first = accounts.ensure()[0]  # новый аккаунт по умолчанию пишет тем же ИИ и на том же языке
    return accounts.create(name, engine=first.engine, language=first.language).public()


def update_account(account_id: str, data: dict) -> dict:
    acc = accounts.get(account_id)
    if "name" in data:
        if not data["name"].strip():
            raise ValueError("Название не может быть пустым")
        acc.name = data["name"].strip()
    if "theme" in data:
        acc.theme = data["theme"].strip() or accounts.DEFAULT_THEME
    if "language" in data:
        acc.language = data["language"].strip() or LANGUAGE
    if "engine" in data:
        if data["engine"] not in engines.ENGINES:
            raise ValueError(f"Неизвестный ИИ: {data['engine']}")
        acc.engine = data["engine"]
    if "post_time" in data:
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(data["post_time"]).strip())
        if not m or int(m[1]) > 23 or int(m[2]) > 59:
            raise ValueError("Время в формате ЧЧ:ММ, например 10:00")
        acc.post_time = f"{int(m[1]):02d}:{m[2]}"
    if "auto_publish" in data:
        if data["auto_publish"] and not acc.creds():
            raise ValueError("Сначала сохраните токен Threads для этого аккаунта")
        acc.auto_publish = bool(data["auto_publish"])
    acc.save()
    return acc.public()


def delete_account(account_id: str) -> None:
    if len(accounts.list_all()) <= 1:
        raise ValueError("Это единственный аккаунт, его нельзя удалить")
    if jobs.get(account_id, {}).get("status") in BUSY:
        raise ValueError("Дождитесь, пока закончится генерация или публикация")
    accounts.delete(account_id)
    jobs.pop(account_id, None)


def save_token(account_id: str, user_id: str, token: str) -> dict:
    acc = accounts.get(account_id)
    token = token.strip() or acc.threads_token
    if not token:
        raise ValueError("Вставьте токен Threads")
    me = threads_pub.whoami(token)  # заодно проверяем, что токен рабочий
    user_id = user_id.strip() or me["id"]
    if user_id != me["id"]:
        raise ValueError(f"Токен принадлежит аккаунту @{me['username']} с ID {me['id']}, а не {user_id}")
    twin = next((a for a in accounts.list_all() if a.id != acc.id and a.threads_user_id == me["id"]), None)
    if twin:
        raise ValueError(f"@{me.get('username')} уже подключён во вкладке «{twin.name}»")
    accounts.set_token(acc, user_id, token, me.get("username", ""))
    acc.save()
    return acc.public()


def _run(account_id: str, status: str, job_fn) -> bool:
    job = job_for(accounts.get(account_id))
    with _lock:
        if job["status"] in BUSY:
            return False
        job.update(status=status, message="", started=time.time())

    def worker():
        try:
            job_fn(job)
            job.update(status="idle")
        except BaseException as e:  # SystemExit из main тоже показываем пользователю
            traceback.print_exc()
            job.update(status="error", message=str(e) or e.__class__.__name__)

    threading.Thread(target=worker, daemon=True).start()
    return True


def do_generate(account_id: str, job: dict) -> None:
    acc = accounts.get(account_id)
    story = main.generate_for(acc)
    path = main.save_draft(story, acc.out_dir)
    job.update(story=story, draft=path, published=False, link=None)


def do_publish(account_id: str, job: dict, posts: list[str]) -> None:
    acc = accounts.get(account_id)
    story = main.fit_story(dict(job["story"], threads_posts=posts))
    main.check_not_recent(story, acc.history())
    posted = main.publish_and_record(acc, story)
    if job["draft"]:
        main.save_draft(story, acc.out_dir, job["draft"])
    job.update(story=story, published=True, link=threads_pub.permalink(acc.creds(), posted["threads"]))


def _powershell(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *args],
                          capture_output=True, text=True, encoding="oem" if os.name == "nt" else None,
                          errors="replace", timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def check_schedule() -> None:
    """hourly — задача новой версии (каждый час), daily — старая (раз в день), none — не установлена."""
    if not schedule["supported"]:
        return
    script = (f"$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue; "
              "if (!$t) {'none'} elseif ($t.Triggers[0].Repetition.Interval) {'hourly'} else {'daily'}")
    try:
        out = _powershell(["-Command", script]).stdout.split()
        schedule["status"] = out[-1] if out and out[-1] in ("none", "daily", "hourly") else "unknown"
    except Exception:
        schedule["status"] = "unknown"


def install_schedule() -> dict:
    if not schedule["supported"]:
        raise ValueError("Расписание ставится только на Windows")
    proc = _powershell(["-File", os.path.join("scripts", "install_task.ps1")])
    if proc.returncode != 0:
        raise RuntimeError(f"Не удалось включить расписание: {(proc.stderr or proc.stdout)[-800:]}")
    check_schedule()
    return schedule


def _background_start() -> None:
    for acc in accounts.ensure():
        accounts.refresh_token_if_needed(acc)
    check_schedule()


class Handler(BaseHTTPRequestHandler):
    page = ""

    def log_message(self, *args):
        pass

    def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            return self._send(200, self.page, "text/html; charset=utf-8")
        if url.path == "/api/state":
            try:
                return self._send(200, state(parse_qs(url.query).get("account", [None])[0]))
            except Exception as e:
                traceback.print_exc()
                return self._send(500, {"error": str(e)})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # Принимаем запросы только со своей страницы.
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self._send(403, {"error": "forbidden"})
        try:
            body = self._json()
            acc_id = body.get("id", "")
            if self.path == "/api/accounts":
                return self._send(200, create_account(body.get("name", "")))
            if self.path == "/api/account":
                return self._send(200, update_account(acc_id, {k: v for k, v in body.items() if k != "id"}))
            if self.path == "/api/account/delete":
                delete_account(acc_id)
                return self._send(200, {"ok": True})
            if self.path == "/api/token":
                return self._send(200, save_token(acc_id, body.get("user_id", ""), body.get("token", "")))
            if self.path == "/api/generate":
                ok = _run(acc_id, "generating", lambda job: do_generate(acc_id, job))
                return self._send(200 if ok else 409, {"ok": ok})
            if self.path == "/api/publish":
                posts = [p.strip() for p in body.get("posts", []) if p.strip()]
                acc = accounts.get(acc_id)
                job = job_for(acc)
                if not job["story"] or not posts:
                    raise ValueError("Нет черновика для публикации")
                if body.get("draft") and body["draft"] != job["draft"]:
                    raise ValueError("Пока вы правили посты, появился новый черновик. Обновите страницу.")
                if not acc.creds():
                    raise ValueError("Сначала сохраните токен Threads для этого аккаунта")
                ok = _run(acc_id, "publishing", lambda job: do_publish(acc_id, job, posts))
                return self._send(200 if ok else 409, {"ok": ok})
            if self.path == "/api/schedule":
                return self._send(200, install_schedule())
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(400, {"error": str(e)})


def run() -> None:
    with open(PAGE_PATH, encoding="utf-8") as f:
        Handler.page = f.read()
    accounts.ensure()  # при первом запуске переносит настройки из .env в accounts/main
    threading.Thread(target=_background_start, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Historian открыт: {url}\nНе закрывайте это окно, пока работаете с ботом.")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
