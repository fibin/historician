"""Шаг 2: превратить досье в посты для Threads."""
import json

from . import llm
from .config import LANGUAGE, THREADS_LIMIT

SYSTEM = f"""Ты автор исторического блога. Пишешь коротко, живо, с интригой в первой фразе,
без канцелярита, без кликбейта и без выдумок: только то, что есть в досье.
Если что-то известно со слов одного мемуариста — так и скажи («по словам его секретаря…»).
Язык постов: {LANGUAGE}. Пиши только на этом языке, даже если досье на другом; имена, названия и цитаты передавай по нормам этого языка. Без хештегов, максимум один уместный эмодзи на весь текст или ни одного.

Формат:
- threads_posts: история для Threads, цепочка из 1–4 постов. Каждый пост не длиннее {THREADS_LIMIT - 20} символов.
  Первый пост — крючок, который заставит читать дальше. Последний заканчивается ссылкой на главный источник.
- person, topic: кто и о чём (коротко, для журнала).
- sources: 2–4 URL из досье, на которые опирается текст."""

SCHEMA = {
    "type": "object",
    "properties": {
        "person": {"type": "string"},
        "topic": {"type": "string"},
        "threads_posts": {"type": "array", "items": {"type": "string"}},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["person", "topic", "threads_posts", "sources"],
    "additionalProperties": False,
}


def write_posts(client, dossier: str, found_urls: list[dict]) -> dict:
    urls = "\n".join(u["url"] for u in found_urls) or "(нет)"
    user = f"Досье:\n{dossier}\n\nURL, которые реально открывались при поиске:\n{urls}"
    response = llm.run(
        client,
        system=SYSTEM,
        user=user,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        effort="medium",
        max_tokens=16000,
    )
    return json.loads(llm.text_of(response))
