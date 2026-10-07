"""Комментарии читателей: бот находит новые, ИИ аккаунта предлагает ответ, человек подтверждает или правит.

Сам бот ничего не отправляет: полностью автоматические ответы выглядят как бот и быстрее всего ловят жалобы.
Всё хранится в accounts/<id>/comments.json: что нашли, черновик ответа и чем закончилось.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

from . import engines, history

CHECK_MINUTES = 60   # окно само проверяет комментарии не чаще раза в час
DAYS = 14            # под постами старше двух недель новых комментариев почти не бывает
NO_PERMISSION = ("Нет доступа к комментариям. В приложении Meta добавьте разрешения threads_read_replies "
                 "и threads_manage_replies (Use cases → Customize → Permissions), получите новый токен и сохраните его.")

SYSTEM = """Ты ведёшь аккаунт в Threads. Тема аккаунта:
{theme}

Тебе дают публикацию аккаунта и новые комментарии читателей к ней. Предложи ответ на каждый.
- Коротко: одно-два предложения, живо и по-человечески, без канцелярита и без «Спасибо за ваш комментарий!».
- По делу: ответь на вопрос, согласись или мягко поправь, добавь деталь или задай встречный вопрос, чтобы разговор продолжился.
- Только то, что есть в публикации или общеизвестно; не выдумывай факты. Если не знаешь, так и скажи.
- Отвечай на языке комментария; если непонятно, на языке: {language}.
- Без хештегов, максимум одно эмодзи.
- Спам, оскорбления, реклама, бессмысленные комментарии и такие, где ответ не нужен (одно эмодзи, «👍»): reply пустой."""

SCHEMA = {
    "type": "object",
    "properties": {"replies": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "reply": {"type": "string"}},
        "required": ["id", "reply"], "additionalProperties": False}}},
    "required": ["replies"],
    "additionalProperties": False,
}


def _path(acc) -> str:
    return os.path.join(acc.folder, "comments.json")


def load(acc) -> dict:
    try:
        with open(_path(acc), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"items": []}


def save(acc, data: dict) -> None:
    from .accounts import _write_json
    _write_json(_path(acc), data)


def is_stale(acc, now: datetime | None = None) -> bool:
    checked = load(acc).get("checked")
    now = now or datetime.now()
    return not checked or now - datetime.fromisoformat(checked) >= timedelta(minutes=CHECK_MINUTES)


def fetch_new(acc, known: set[str], today: date | None = None) -> list[dict]:
    """Комментарии под свежими постами, на которые аккаунт ещё не ответил и которых нет в known."""
    from .publishers import threads as threads_pub

    creds, me = acc.creds(), (acc.threads_username or "").lower()
    since = ((today or date.today()) - timedelta(days=DAYS)).isoformat()
    found = []
    for entry in acc.history():
        post_id = (entry.get("posted") or {}).get("threads")
        if not post_id or entry.get("date", "") < since:
            continue
        replies = threads_pub.conversation(creds, post_id)
        ours = [r for r in replies if (r.get("username") or "").lower() == me]
        answered = {(r.get("replied_to") or {}).get("id") for r in ours}
        for r in replies:
            if (r.get("username") or "").lower() == me or r["id"] in known or r["id"] in answered:
                continue
            if r.get("hide_status") not in (None, "NOT_HUSHED", "UNHUSHED") or not (r.get("text") or "").strip():
                continue
            found.append({"id": r["id"], "post_id": post_id, "subject": history.subject_of(entry),
                          "topic": entry.get("topic", ""), "link": (entry.get("posted") or {}).get("link"),
                          "username": r.get("username", ""), "text": r.get("text", ""),
                          "timestamp": r.get("timestamp", ""), "status": "new", "draft": ""})
    return found


def draft_replies(acc, new: list[dict]) -> None:
    """ИИ аккаунта пишет черновики ответов: по одному запросу на пост."""
    by_post: dict[str, list[dict]] = {}
    for c in new:
        by_post.setdefault(c["post_id"], []).append(c)
    entries = {(e.get("posted") or {}).get("threads"): e for e in acc.history()}
    system = SYSTEM.replace("{theme}", acc.theme.strip()).replace("{language}", acc.language)
    for post_id, items in by_post.items():
        e = entries.get(post_id, {})
        user = (f"Публикация: {history.subject_of(e)} — {e.get('topic', '')}\n"
                f"Начало: {e.get('hook', '')}\nИсточники: {', '.join(e.get('sources') or [])}\n\n"
                "Комментарии:\n" + "\n".join(f"[{c['id']}] @{c['username']}: {c['text']}" for c in items))
        try:
            answer = engines.ask(acc.engine, system, user, SCHEMA)
        except Exception as ex:  # без черновика человек напишет ответ сам
            print(f"[{acc.name}] ИИ не предложил ответы: {ex}", file=sys.stderr)
            continue
        drafts = {r["id"]: r["reply"].strip() for r in answer.get("replies") or []}
        for c in items:
            c["draft"] = drafts.get(c["id"], "")
            c["suggest_skip"] = c["id"] in drafts and not c["draft"]


def check(acc, now: datetime | None = None) -> dict:
    """Ищет новые комментарии и готовит черновики ответов. Ошибки пишутся в comments.json."""
    from .publishers import threads as threads_pub

    now = now or datetime.now()
    data = load(acc)
    data.update(checked=now.isoformat(timespec="seconds"), error="")
    try:
        new = fetch_new(acc, {c["id"] for c in data["items"]}, now.date())
    except threads_pub.NoPermission:
        data["error"] = NO_PERMISSION
        new = []
    except Exception as e:
        data["error"] = f"Не удалось проверить комментарии: {e}"
        new = []
    if new:
        draft_replies(acc, new)
    # перечитываем перед записью: пока ИИ писал, человек мог ответить на другой комментарий
    fresh = load(acc)
    data["items"] = fresh.get("items", []) + new
    save(acc, data)
    return data


def _find(data: dict, comment_id: str) -> dict:
    item = next((c for c in data["items"] if c["id"] == comment_id), None)
    if not item:
        raise ValueError("Такого комментария нет")
    return item


def send(acc, comment_id: str, text: str) -> dict:
    from .publishers import threads as threads_pub

    text = text.strip()
    if not text:
        raise ValueError("Напишите ответ")
    data = load(acc)
    item = _find(data, comment_id)
    if item["status"] == "answered":
        raise ValueError("На этот комментарий уже ответили")
    try:
        reply_id = threads_pub.reply(acc.creds(), comment_id, text)
    except threads_pub.NoPermission:
        raise ValueError(NO_PERMISSION)
    data = load(acc)
    item = _find(data, comment_id)
    item.update(status="answered", reply=text, reply_id=reply_id, answered=datetime.now().isoformat(timespec="seconds"))
    save(acc, data)
    return item


def skip(acc, comment_id: str) -> None:
    data = load(acc)
    _find(data, comment_id)["status"] = "skipped"
    save(acc, data)


def pending(acc) -> dict:
    """Для окна: комментарии, которые ждут решения, новые сверху."""
    data = load(acc)
    items = sorted((c for c in data["items"] if c["status"] == "new"), key=lambda c: c.get("timestamp", ""), reverse=True)
    return {"checked": data.get("checked"), "error": data.get("error", ""), "items": items}
