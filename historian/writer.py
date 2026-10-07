"""Шаг 2: превратить досье в посты для Threads."""
import json

from . import llm
from .config import THREADS_LIMIT

SYSTEM = """Ты автор аккаунта в Threads. Тема аккаунта и пожелания к контенту:
{theme}

Пиши коротко, живо, с интригой в первой фразе, без канцелярита, без кликбейта и без выдумок:
только то, что есть в досье. Если что-то спорно или известно из одного источника — так и скажи.
Тон, стиль и подачу подбирай под тему аккаунта; если тема просит другой формат, следуй ей.
Язык постов: {language}. Пиши только на этом языке, даже если досье на другом; имена, названия и цитаты передавай по нормам этого языка. Без хештегов, максимум один уместный эмодзи на весь текст или ни одного, если тема не просит иначе.

Формат ответа:
- threads_posts: цепочка из 1–10 постов: столько, сколько нужно материалу, без воды. Каждый пост не длиннее {max_len} символов.
  Первый пост — крючок, который заставит читать дальше. Последний заканчивается ссылкой на главный источник, если тема не просит иначе.
- subject: о ком или о чём публикация (коротко, для журнала: по нему бот не даёт повторяться).
- topic: одна строка, о чём публикация.
- sources: 2–4 URL из досье, на которые опирается текст."""

SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "topic": {"type": "string"},
        "threads_posts": {"type": "array", "items": {"type": "string"}},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subject", "topic", "threads_posts", "sources"],
    "additionalProperties": False,
}


def system_prompt(theme: str, language: str) -> str:
    return (SYSTEM.replace("{theme}", theme.strip()).replace("{language}", language.strip())
            .replace("{max_len}", str(THREADS_LIMIT - 20)))


def write_posts(client, dossier: str, found_urls: list[dict], theme: str, language: str) -> dict:
    urls = "\n".join(u["url"] for u in found_urls) or "(нет)"
    user = f"Досье:\n{dossier}\n\nURL, которые реально открывались при поиске:\n{urls}"
    response = llm.run(
        client,
        system=system_prompt(theme, language),
        user=user,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        effort="medium",
        max_tokens=16000,
    )
    return json.loads(llm.text_of(response))
