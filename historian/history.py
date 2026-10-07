"""Журнал опубликованных историй: не повторяем людей и сюжеты."""
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


def summary_for_prompt(entries: list[dict], limit: int = 300) -> str:
    """Короткий список уже использованных тем для промпта."""
    if not entries:
        return "(пока ничего не публиковалось)"
    recent = entries[-limit:]
    return "\n".join(f"- {e['person']}: {e['topic']}" for e in recent)


def used_people(entries: list[dict], recent: int = 60) -> set[str]:
    return {e["person"].strip().lower() for e in entries[-recent:]}


def add(entries: list[dict], story: dict, posted: dict) -> list[dict]:
    return entries + [{
        "date": date.today().isoformat(),
        "person": story["person"],
        "topic": story["topic"],
        "sources": story["sources"],
        "engine": story.get("engine"),
        "posted": posted,
    }]
