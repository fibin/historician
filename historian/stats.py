"""Статистика аккаунта: сколько людей увидело посты и как отреагировало.

Цифры каждого поста хранятся в его записи журнала (поле stats), подписчики — в accounts/<id>/stats.json.
Лучшие и худшие посты попадают в промпт, чтобы ИИ подстраивался под то, что заходит аудитории.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta

from . import history

REFRESH_HOURS = 6     # не чаще: Threads обновляет цифры не мгновенно, а у API есть лимиты
TRACK_DAYS = 30       # посты старше месяца почти не набирают, их цифры больше не обновляем
SETTLE_DAYS = 2       # в промпт берём посты не моложе двух дней, пока цифры не устоялись
MIN_FOR_PROMPT = 4    # меньше постов со статистикой — сравнивать нечего
PROMPT_EACH = 5       # сколько лучших и худших постов показывать ИИ
NO_PERMISSION = ("Нет доступа к статистике. В приложении Meta добавьте разрешение threads_manage_insights "
                 "(Use cases → Customize → Permissions), получите новый токен и сохраните его ниже.")


def _path(acc) -> str:
    return os.path.join(acc.folder, "stats.json")


def load(acc) -> dict:
    try:
        with open(_path(acc), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(acc, data: dict) -> None:
    from .accounts import _write_json
    _write_json(_path(acc), data)


def interactions(s: dict) -> int:
    return sum(s.get(k, 0) for k in ("likes", "replies", "reposts", "quotes", "shares"))


def score(s: dict) -> float:
    """Насколько пост зацепил: охват плюс реакции. Ответы, репосты и цитаты весят больше лайков:
    именно они приводят новых читателей."""
    return s.get("views", 0) + 5 * s.get("likes", 0) + 15 * (s.get("replies", 0) + s.get("reposts", 0)
                                                             + s.get("quotes", 0) + s.get("shares", 0))


def is_stale(acc, now: datetime | None = None) -> bool:
    checked = load(acc).get("checked")
    now = now or datetime.now()
    return not checked or now - datetime.fromisoformat(checked) >= timedelta(hours=REFRESH_HOURS)


def refresh(acc, now: datetime | None = None, force: bool = False) -> dict:
    """Обновляет цифры свежих постов и число подписчиков. Ошибки не роняют бота, а пишутся в stats.json."""
    from .publishers import threads as threads_pub

    now = now or datetime.now()
    creds = acc.creds()
    if not creds or not (force or is_stale(acc, now)):
        return load(acc)
    data = load(acc)
    data.update(checked=now.isoformat(timespec="seconds"), error="")
    fresh: dict[str, dict] = {}
    try:
        data["followers"] = threads_pub.followers(creds)
        log = [x for x in data.get("followers_log", []) if x["date"] != now.date().isoformat()]
        data["followers_log"] = (log + [{"date": now.date().isoformat(), "n": data["followers"]}])[-120:]
        since = (now.date() - timedelta(days=TRACK_DAYS)).isoformat()
        for e in acc.history():
            post_id = (e.get("posted") or {}).get("threads")
            if post_id and (e.get("date", "") >= since or "stats" not in e):
                fresh[post_id] = threads_pub.post_insights(creds, post_id)
    except threads_pub.NoPermission:
        data["error"] = NO_PERMISSION
    except Exception as e:  # сеть, удалённый пост, истёкший токен: попробуем в следующий раз
        print(f"[{acc.name}] не удалось получить статистику Threads: {e}", file=sys.stderr)
        data["error"] = f"Не удалось получить статистику: {e}"
    if fresh:
        # журнал перечитываем прямо перед записью, чтобы не затереть только что опубликованный пост
        entries = acc.history()
        for e in entries:
            post_id = (e.get("posted") or {}).get("threads")
            if post_id in fresh:
                e["stats"], e["stats_at"] = fresh[post_id], data["checked"]
        history.save(acc.history_path, entries)
    _save(acc, data)
    return data


def followers_change(data: dict, days: int = 7, today: date | None = None) -> int | None:
    """Сколько подписчиков прибавилось за неделю; None, если неделю назад ещё не считали."""
    log = data.get("followers_log") or []
    if not log:
        return None
    since = ((today or date.today()) - timedelta(days=days)).isoformat()
    before = [x for x in log if x["date"] <= since]
    return log[-1]["n"] - before[-1]["n"] if before else None


def summary(acc, limit: int = 10) -> dict:
    """Для окна: подписчики и цифры последних постов."""
    data = load(acc)
    posts = []
    for e in reversed(acc.history()):
        if len(posts) >= limit:
            break
        posted = e.get("posted") or {}
        posts.append({"date": e.get("date"), "subject": history.subject_of(e), "topic": e.get("topic", ""),
                      "link": posted.get("link"), "stats": e.get("stats")})
    return {"followers": data.get("followers"), "week": followers_change(data), "checked": data.get("checked"),
            "error": data.get("error", ""), "posts": posts}


def _line(e: dict) -> str:
    s = e["stats"]
    hook = (e.get("hook") or "").strip().replace("\n", " ")
    hook = f" | начало: «{hook[:160]}»" if hook else ""
    return (f"- {history.subject_of(e)}: {e.get('topic', '')}{hook} | {s.get('views', 0)} просмотров, "
            f"{s.get('likes', 0)} лайков, {s.get('replies', 0)} ответов, "
            f"{s.get('reposts', 0) + s.get('quotes', 0) + s.get('shares', 0)} репостов")


def feedback_for_prompt(entries: list[dict], today: date | None = None) -> str:
    """Лучшие и худшие публикации аккаунта для промпта. Пусто, пока сравнивать не с чем."""
    settled = ((today or date.today()) - timedelta(days=SETTLE_DAYS)).isoformat()
    rated = [e for e in entries if e.get("stats") and e.get("date", "") <= settled]
    if len(rated) < MIN_FOR_PROMPT:
        return ""
    rated.sort(key=lambda e: score(e["stats"]), reverse=True)
    n = min(PROMPT_EACH, len(rated) // 2)
    return ("Как читатели приняли прошлые публикации этого аккаунта.\n"
            "Зашли лучше всего:\n" + "\n".join(_line(e) for e in rated[:n]) + "\n"
            "Зашли хуже всего:\n" + "\n".join(_line(e) for e in rated[-n:]) + "\n"
            "Подумай, чем удачные отличаются от неудачных (тип материала, первая фраза, подача, длина), "
            "и выбирай материал и подачу ближе к удачным. Предметы при этом не повторяй.")
