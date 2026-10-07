"""Журнал опубликованного в аккаунте: не повторяем предметы и темы."""
import json
import os
from datetime import date


def load(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path: str, entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
        f.write("\n")


def subject_of(item: dict) -> str:
    """О ком или о чём публикация. Старые записи и черновики хранили это в поле person."""
    return item.get("subject") or item.get("person") or ""


def key(item: dict) -> str:
    return subject_of(item).strip().lower()


def summary_for_prompt(entries: list[dict], limit: int = 300) -> str:
    """Короткий список уже использованных тем для промпта."""
    if not entries:
        return "(пока ничего не публиковалось)"
    recent = entries[-limit:]
    return "\n".join(f"- {subject_of(e)}: {e['topic']}" for e in recent)


def used_subjects(entries: list[dict], recent: int = 60) -> set[str]:
    return {key(e) for e in entries[-recent:]}


def add(entries: list[dict], story: dict, posted: dict) -> list[dict]:
    return entries + [{
        "date": date.today().isoformat(),
        "subject": subject_of(story),
        "topic": story["topic"],
        "sources": story["sources"],
        "engine": story.get("engine"),
        "posted": posted,
    }]
