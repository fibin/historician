"""Ежедневный запуск: найти историю → написать посты → (по флагу) опубликовать.

    python -m historian.main                 # черновик в out/, ничего не публикует
    python -m historian.main --publish       # найти и опубликовать
    python -m historian.main --from-draft out/2026-10-07.json --publish   # опубликовать готовый черновик
    python -m historian.main --refresh-threads-token
"""
import argparse
import json
import os
import sys
from datetime import date

from . import history, research, writer
from .config import HISTORY_PATH, THREADS_LIMIT, ThreadsCredentials, env_flag
from .textfit import fit, plain_length

MAX_ATTEMPTS = 3


def fit_story(story: dict) -> dict:
    story["threads_posts"] = fit(story["threads_posts"], THREADS_LIMIT, plain_length)
    return story


def generate(engine: str, entries: list[dict]) -> dict:
    """engine: claude-code / codex / gemini — через подписку (см. engines.py), api — Claude API по ключу."""
    client = None
    if engine == "api":
        import anthropic
        client = anthropic.Anthropic()
    used = history.used_people(entries)
    summary = history.summary_for_prompt(entries)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if engine != "api":
            from . import engines
            story = engines.generate_story(engine, summary)
        else:
            dossier, urls = research.find_story(client, summary)
            story = writer.write_posts(client, dossier, urls)
            story["dossier"] = dossier
            story["engine"] = "api"
        if story["person"].strip().lower() in used:
            print(f"[{attempt}] {story['person']} уже был недавно, ищу другую историю", file=sys.stderr)
            continue
        return fit_story(story)
    raise RuntimeError("Не удалось найти новую историю")


def publish(story: dict) -> dict:
    from .publishers import threads as threads_pub

    creds = ThreadsCredentials.from_env()
    if not creds:
        raise SystemExit("Нет ключей Threads (THREADS_USER_ID, THREADS_ACCESS_TOKEN)")
    ids = threads_pub.post_thread(creds, story["threads_posts"])
    return {"threads": ids[0]}


def check_not_recent(story: dict, entries: list[dict]) -> None:
    if story["person"].strip().lower() in history.used_people(entries):
        raise SystemExit(f"{story['person']} уже был недавно, нужна другая история")


def save_draft(story: dict, out_dir: str = "out") -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{date.today().isoformat()}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(story, f, ensure_ascii=False, indent=2)
    return path


def publish_and_record(story: dict) -> dict:
    """Публикует и записывает в журнал. Журнал перечитывается, чтобы не затереть чужие записи."""
    posted = publish(story)
    history.save(HISTORY_PATH, history.add(history.load(HISTORY_PATH), story, posted))
    return posted


def print_preview(story: dict) -> None:
    print(f"\n=== {story['person']} — {story['topic']} ===\n")
    for i, p in enumerate(story["threads_posts"], 1):
        print(f"[{i}/{len(story['threads_posts'])}, {len(p)} симв.] {p}\n")
    print("Источники:", *story["sources"], sep="\n  ")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", default=env_flag("HISTORIAN_PUBLISH"))
    ap.add_argument("--from-draft")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--refresh-threads-token", action="store_true")
    ap.add_argument("--engine", choices=["claude-code", "codex", "gemini", "api"],
                    default=os.environ.get("HISTORIAN_ENGINE", "claude-code"),
                    help="claude-code (по умолчанию), codex (ChatGPT), gemini — через подписку; api — через ключ Claude API")
    args = ap.parse_args(argv)

    if args.refresh_threads_token:
        from .publishers.threads import refresh_token
        print(json.dumps(refresh_token(os.environ["THREADS_ACCESS_TOKEN"]), indent=2))
        return

    entries = history.load(HISTORY_PATH)
    if args.from_draft:
        with open(args.from_draft, encoding="utf-8") as f:
            story = fit_story(json.load(f))
        check_not_recent(story, entries)
    else:
        story = generate(args.engine, entries)
        draft = save_draft(story, args.out_dir)
        print(f"Черновик сохранён: {draft}", file=sys.stderr)

    print_preview(story)
    if not args.publish:
        print("\nРежим черновика: ничего не опубликовано (добавьте --publish).", file=sys.stderr)
        return

    posted = publish_and_record(story)
    print("Опубликовано:", json.dumps(posted, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
