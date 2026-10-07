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
from .config import HISTORY_PATH, THREADS_LIMIT, X_LIMIT, ThreadsCredentials, XCredentials, env_flag
from .textfit import fit, plain_length, x_length

MAX_ATTEMPTS = 3


def fit_story(story: dict) -> dict:
    story["x_posts"] = fit(story["x_posts"], X_LIMIT, x_length)
    story["threads_posts"] = fit(story["threads_posts"], THREADS_LIMIT, plain_length)
    return story


def generate(client, entries: list[dict]) -> dict:
    used = history.used_people(entries)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        dossier, urls = research.find_story(client, history.summary_for_prompt(entries))
        story = writer.write_posts(client, dossier, urls)
        if story["person"].strip().lower() in used:
            print(f"[{attempt}] {story['person']} уже был недавно, ищу другую историю", file=sys.stderr)
            continue
        story["dossier"] = dossier
        return fit_story(story)
    raise RuntimeError("Не удалось найти новую историю")


def publish(story: dict, want_x: bool, want_threads: bool) -> dict:
    from .publishers import threads as threads_pub
    from .publishers import x as x_pub

    posted = {}
    if want_x:
        creds = XCredentials.from_env()
        if not creds:
            raise SystemExit("Нет ключей X (X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET)")
        ids = x_pub.post_thread(creds, story["x_posts"])
        posted["x"] = f"https://x.com/i/status/{ids[0]}"
    if want_threads:
        creds = ThreadsCredentials.from_env()
        if not creds:
            raise SystemExit("Нет ключей Threads (THREADS_USER_ID, THREADS_ACCESS_TOKEN)")
        ids = threads_pub.post_thread(creds, story["threads_posts"])
        posted["threads"] = ids[0]
    return posted


def print_preview(story: dict) -> None:
    print(f"\n=== {story['person']} — {story['topic']} ===\n")
    print("--- X ---")
    for i, p in enumerate(story["x_posts"], 1):
        print(f"[{i}/{len(story['x_posts'])}, {x_length(p)} симв.] {p}\n")
    print("--- Threads ---")
    for i, p in enumerate(story["threads_posts"], 1):
        print(f"[{i}/{len(story['threads_posts'])}, {len(p)} симв.] {p}\n")
    print("Источники:", *story["sources"], sep="\n  ")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", default=env_flag("HISTORIAN_PUBLISH"))
    ap.add_argument("--no-x", action="store_true")
    ap.add_argument("--no-threads", action="store_true")
    ap.add_argument("--from-draft")
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--refresh-threads-token", action="store_true")
    args = ap.parse_args(argv)

    if args.refresh_threads_token:
        from .publishers.threads import refresh_token
        print(json.dumps(refresh_token(os.environ["THREADS_ACCESS_TOKEN"]), indent=2))
        return

    entries = history.load(HISTORY_PATH)
    if args.from_draft:
        with open(args.from_draft, encoding="utf-8") as f:
            story = fit_story(json.load(f))
        if story["person"].strip().lower() in history.used_people(entries):
            raise SystemExit(f"{story['person']} уже был недавно, нужна другая история")
    else:
        import anthropic
        story = generate(anthropic.Anthropic(), entries)
        os.makedirs(args.out_dir, exist_ok=True)
        draft = os.path.join(args.out_dir, f"{date.today().isoformat()}.json")
        with open(draft, "w", encoding="utf-8") as f:
            json.dump(story, f, ensure_ascii=False, indent=2)
        print(f"Черновик сохранён: {draft}", file=sys.stderr)

    print_preview(story)
    if not args.publish:
        print("\nРежим черновика: ничего не опубликовано (добавьте --publish).", file=sys.stderr)
        return

    posted = publish(story, want_x=not args.no_x, want_threads=not args.no_threads)
    history.save(HISTORY_PATH, history.add(entries, story, posted))
    print("Опубликовано:", json.dumps(posted, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
