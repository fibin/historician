"""Шаг 2: превратить досье в посты для Threads."""
import json

from . import llm
from .config import THREADS_LIMIT

SYSTEM = """Ты автор аккаунта в Threads. Тема аккаунта и пожелания к контенту:
{theme}

Пиши коротко, живо, с интригой в первой фразе, без канцелярита, без кликбейта{truth}
Тон, стиль и подачу подбирай под тему аккаунта; если тема просит другой формат, следуй ей.
Язык постов: {language}. Пиши только на этом языке, даже если досье на другом; имена, названия и цитаты передавай по нормам этого языка. Без хештегов, максимум один уместный эмодзи на весь текст или ни одного, если тема не просит иначе.

Формат ответа:
- threads_posts: {posts}. Каждый пост не длиннее {max_len} символов.
  Первый пост — крючок: от него зависит, раскроют ли цепочку. Придумай про себя три разных начала
  (неожиданный факт или цифра, парадокс, конфликт или загадка) и возьми самое сильное. Первая фраза понятна
  без контекста и цепляет с первой секунды; не начинай с даты, «Знаете ли вы» или «Сегодня расскажу».
  Последний пост заканчивается коротким вопросом к читателям, на который легко ответить
  {ending}
- subject: о ком или о чём публикация (коротко, для журнала: по нему бот не даёт повторяться).
- topic: одна строка, о чём публикация.
{sources}
  Пустой список, если показывать нечего или тема просит без картинок."""

# Что меняется в промпте, когда аккаунт ищет реальные истории и когда придумывает свои (креативный режим).
FACTS = {
    "truth": " и без выдумок:\nтолько то, что есть в досье. Если что-то спорно или известно из одного источника — так и скажи.",
    "ending": "(их мнение, опыт, догадка, «а вы знали?»), и ссылкой на главный источник отдельной строкой после вопроса,\n"
              "  если тема не просит иначе. Вопрос живой и по делу, не «Что думаете?».",
    "sources": "- sources: 2–4 URL из досье, на которые опирается текст.\n"
               "- image_queries: 2–3 поисковых запроса на английском для Wikimedia Commons, чтобы найти картинку к первому посту:\n"
               "  портрет человека, место, предмет, событие, гравюра, карта. От самого точного (имя + что именно) к более общему.",
}
CREATIVE = {
    "truth": ".\nЭто твоя собственная выдуманная история по плану из досье: рассказывай её как живую историю,\n"
             "держи напряжение до конца, развязку не выдавай раньше времени. Не пиши, что это вымысел, если тема не просит.",
    "ending": "(их догадка, похожий случай, как бы они поступили), если тема не просит иначе. Без ссылок.\n"
              "  Вопрос живой и по делу, не «Что думаете?».",
    "sources": "- sources: пустой список, история придумана.\n"
               "- image_queries: 1–3 разных описания картинки к первому посту на английском для генератора изображений,\n"
               "  по 1–3 предложения: что в кадре, настроение, свет, стиль (например, photo, film grain, oil painting).\n"
               "  Атмосферно и без спойлера развязки; без текста на картинке, без реальных известных людей.",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "topic": {"type": "string"},
        "threads_posts": {"type": "array", "items": {"type": "string"}},
        "sources": {"type": "array", "items": {"type": "string"}},
        "image_queries": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subject", "topic", "threads_posts", "sources", "image_queries"],
    "additionalProperties": False,
}


DEFAULT_POSTS = (1, 10)  # сколько постов в цепочке, если в аккаунте не задано иначе
MAX_POSTS = 25


def posts_rule(posts: tuple[int, int]) -> str:
    lo, hi = posts
    if lo == hi == 1:
        return "один пост, без цепочки"
    if lo == hi:
        return f"цепочка ровно из {hi} постов"
    return f"цепочка из {lo}–{hi} постов: столько, сколько нужно материалу, без воды"


def system_prompt(theme: str, language: str, posts: tuple[int, int] = DEFAULT_POSTS, creative: bool = False) -> str:
    text = SYSTEM
    for key, value in (CREATIVE if creative else FACTS).items():
        text = text.replace("{" + key + "}", value)
    return (text.replace("{theme}", theme.strip()).replace("{language}", language.strip())
            .replace("{posts}", posts_rule(posts)).replace("{max_len}", str(THREADS_LIMIT - 20)))


def write_posts(client, dossier: str, found_urls: list[dict], theme: str, language: str, feedback: str = "",
                posts: tuple[int, int] = DEFAULT_POSTS, creative: bool = False) -> dict:
    urls = "\n".join(u["url"] for u in found_urls) or "(нет)"
    user = f"Досье:\n{dossier}" if creative else f"Досье:\n{dossier}\n\nURL, которые реально открывались при поиске:\n{urls}"
    if feedback:
        user += f"\n\n{feedback}"
    response = llm.run(
        client,
        system=system_prompt(theme, language, posts, creative),
        user=user,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        effort="medium",
        max_tokens=16000,
    )
    return json.loads(llm.text_of(response))
