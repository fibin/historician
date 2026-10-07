"""Запуск из консоли и по расписанию.

    python -m historian.main                          # черновик для первого аккаунта, ничего не публикует
    python -m historian.main --account nauka          # черновик для аккаунта nauka (папка в accounts/)
    python -m historian.main --publish                # найти и опубликовать
    python -m historian.main --from-draft accounts/main/out/2026-10-07_100000.json --publish
    python -m historian.main --due                    # для планировщика: публикует там, где пришло время
    python -m historian.main --refresh-threads-token  # продлить токены Threads всех аккаунтов
"""
import argparse
import json
import os
import sys
import traceback
from datetime import date, datetime

from . import accounts, history, images, research, stats, writer
from .config import LANGUAGE, THREADS_LIMIT, ThreadsCredentials, env_flag
from .textfit import fit, plain_length

MAX_ATTEMPTS = 3        # сколько раз искать другой материал, если такой предмет уже был
MAX_DAILY_ATTEMPTS = 2  # сколько раз в день планировщик пробует опубликовать, если что-то сломалось


def normalize(story: dict) -> dict:
    """Черновики старых версий хранили предмет публикации в поле person."""
    if "subject" not in story and "person" in story:
        story["subject"] = story.pop("person")
    return story


def fit_story(story: dict) -> dict:
    story = normalize(story)
    story["threads_posts"] = fit(story["threads_posts"], THREADS_LIMIT, plain_length)
    return story


def add_images(story: dict) -> dict:
    """Варианты картинки с Wikimedia Commons; первая выбрана, в окне можно сменить или убрать."""
    story["images"] = images.find(story.get("image_queries") or [])
    story["image"] = 0 if story["images"] else None
    return story


def generate(engine: str, entries: list[dict], theme: str, language: str = LANGUAGE,
             with_image: bool = True) -> dict:
    """engine: claude-code / codex / gemini — через подписку (см. engines.py), api — Claude API по ключу."""
    if not theme.strip():
        raise SystemExit("Опишите в настройках аккаунта, о чём он: без темы ИИ не знает, что искать")
    client = None
    if engine == "api":
        import anthropic
        client = anthropic.Anthropic()
    used = history.used_subjects(entries)
    summary = history.summary_for_prompt(entries)
    feedback = stats.feedback_for_prompt(entries)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if engine != "api":
            from . import engines
            story = engines.generate_story(engine, summary, theme, language, feedback)
        else:
            dossier, urls = research.find_story(client, summary, theme, feedback)
            story = writer.write_posts(client, dossier, urls, theme, language, feedback)
            story["dossier"] = dossier
            story["engine"] = "api"
        if history.key(story) in used:
            print(f"[{attempt}] «{history.subject_of(story)}» уже был недавно, ищу другой материал", file=sys.stderr)
            continue
        story = fit_story(story)
        return add_images(story) if with_image else story
    raise RuntimeError("Не удалось найти новый материал: ИИ трижды предложил то, что уже было")


def generate_for(acc: accounts.Account, engine: str | None = None) -> dict:
    stats.refresh(acc)  # свежие цифры, чтобы ИИ видел, что заходит
    return generate(engine or acc.engine, acc.history(), acc.theme, acc.language, acc.with_image)


def publish(story: dict, creds: ThreadsCredentials | None) -> dict:
    from .publishers import threads as threads_pub

    if not creds:
        raise SystemExit("У этого аккаунта нет ID и токена Threads")
    img = images.chosen(story)
    posts = list(story["threads_posts"])
    if img and images.credit(img):
        posts[-1] = posts[-1].rstrip() + "\n\n" + images.credit(img)
        posts = fit(posts, THREADS_LIMIT, plain_length)
    ids = threads_pub.post_thread(creds, posts, image_url=img and img["url"])
    posted = {"threads": ids[0]}
    if img:
        posted["image"] = img["page"]
    return posted


def check_not_recent(story: dict, entries: list[dict]) -> None:
    if history.key(story) in history.used_subjects(entries):
        raise SystemExit(f"«{history.subject_of(story)}» уже был в этом аккаунте недавно, нужен другой материал")


def save_draft(story: dict, out_dir: str, path: str | None = None) -> str:
    """Новый черновик получает имя по дате и времени, существующий (path) перезаписывается."""
    os.makedirs(out_dir, exist_ok=True)
    path = path or os.path.join(out_dir, f"{datetime.now():%Y-%m-%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)
    return path


def permalink(acc: accounts.Account, post_id: str) -> str | None:
    """Ссылка на пост в Threads; None, если Threads её не отдал."""
    from .publishers import threads as threads_pub

    try:
        return threads_pub.permalink(acc.creds(), post_id)
    except Exception:
        return None


def publish_and_record(acc: accounts.Account, story: dict) -> dict:
    """Публикует и записывает в журнал аккаунта вместе со ссылкой на пост.
    Журнал перечитывается, чтобы не затереть чужие записи."""
    posted = publish(story, acc.creds())
    posted["link"] = permalink(acc, posted["threads"])
    history.save(acc.history_path, history.add(acc.history(), story, posted))
    return posted


def print_preview(story: dict) -> None:
    print(f"\n=== {history.subject_of(story)} — {story['topic']} ===\n")
    for i, p in enumerate(story["threads_posts"], 1):
        print(f"[{i}/{len(story['threads_posts'])}, {len(p)} симв.] {p}\n")
    print("Источники:", *story["sources"], sep="\n  ")


def is_due(acc: accounts.Account, now: datetime) -> bool:
    """Пора ли публиковать: включена автопубликация, время прошло, сегодня в аккаунте ещё не было поста.
    Если компьютер был выключен в нужный час, пост выйдет при первом запуске после включения."""
    return (acc.auto_publish and acc.creds() is not None and bool(acc.theme.strip())
            and now.strftime("%H:%M") >= acc.post_time
            and not accounts.posted_today(acc, now.date())
            and accounts.attempts_today(acc, now.date()) < MAX_DAILY_ATTEMPTS)


def run_due(now: datetime | None = None) -> None:
    """Раз в час из планировщика Windows: продлевает токены и публикует там, где пришло время."""
    now = now or datetime.now()
    for acc in accounts.ensure():
        accounts.refresh_token_if_needed(acc, now.date())
        stats.refresh(acc, now)
        if not is_due(acc, now):
            continue
        accounts.note_attempt(acc, now.date())
        print(f"{now:%Y-%m-%d %H:%M} [{acc.name}] готовлю пост ({acc.engine})", flush=True)
        try:
            story = generate_for(acc)
            draft = save_draft(story, acc.out_dir)
            print(f"[{acc.name}] черновик: {draft}", flush=True)
            posted = publish_and_record(acc, story)
            print(f"[{acc.name}] опубликовано: {history.subject_of(story)} — {story['topic']} {posted}", flush=True)
        except (Exception, SystemExit) as e:  # один сломанный аккаунт не мешает остальным
            print(f"[{acc.name}] ошибка: {e}", flush=True)
            traceback.print_exc()


def _log_to(log_dir: str) -> None:
    """При запуске без окна (pythonw) пишем вывод в logs/<дата>.log."""
    os.makedirs(log_dir, exist_ok=True)
    log = open(os.path.join(log_dir, f"{date.today().isoformat()}.log"), "a", encoding="utf-8")
    sys.stdout = sys.stderr = log


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", help="id аккаунта (папка в accounts/), по умолчанию первый")
    ap.add_argument("--publish", action="store_true", default=env_flag("HISTORIAN_PUBLISH"))
    ap.add_argument("--from-draft")
    ap.add_argument("--due", action="store_true", help="для планировщика: опубликовать там, где пришло время")
    ap.add_argument("--log-dir", help="писать вывод в файл в этой папке")
    ap.add_argument("--refresh-threads-token", action="store_true")
    ap.add_argument("--engine", choices=["claude-code", "codex", "gemini", "api"],
                    help="другой ИИ на этот запуск: claude-code, codex (ChatGPT), gemini — через подписку; "
                         "api — через ключ Claude API. По умолчанию ИИ из настроек аккаунта")
    args = ap.parse_args(argv)
    if args.log_dir:
        _log_to(args.log_dir)

    if args.due:
        return run_due()

    all_accounts = accounts.ensure()
    if args.refresh_threads_token:
        for a in all_accounts:
            if accounts.refresh_token_if_needed(a, force=True):
                print(f"[{a.name}] токен продлён до {a.token_expires}")
        return

    acc = accounts.get(args.account) if args.account else all_accounts[0]
    if args.from_draft:
        with open(args.from_draft, encoding="utf-8") as f:
            story = fit_story(json.load(f))
        check_not_recent(story, acc.history())
    else:
        story = generate_for(acc, args.engine)
        draft = save_draft(story, acc.out_dir)
        print(f"Черновик сохранён: {draft}", file=sys.stderr)

    print_preview(story)
    if not args.publish:
        print("\nРежим черновика: ничего не опубликовано (добавьте --publish).", file=sys.stderr)
        return

    posted = publish_and_record(acc, story)
    print("Опубликовано:", json.dumps(posted, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
