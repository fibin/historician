"""Картинка к посту из Wikimedia Commons: архивные фото, картины, гравюры, карты.

На Commons только свободные файлы (общественное достояние или открытые лицензии), поэтому их можно публиковать.
Для лицензий, которые требуют указать автора (CC BY, CC BY-SA), бот добавляет подпись в конец последнего поста.
Threads сам скачивает картинку по ссылке, поэтому хранить файлы у себя не нужно.
"""
import re
import sys

import requests

API = "https://commons.wikimedia.org/w/api.php"
UA = "HistorianBot/1.0 (https://github.com/fibin/historician)"  # Wikimedia просит представляться
WIDTH = 1280      # стандартный размер миниатюр Commons; Threads принимает до 1440 по ширине
PREVIEW = 330     # маленькая копия для окна
MIN_WIDTH = 500   # мельче выглядит плохо
OPTIONS = 6       # сколько вариантов показывать в окне


def _plain(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html or "")
    return re.sub(r"\s+", " ", text).strip()


def _image(page: dict) -> dict | None:
    info = (page.get("imageinfo") or [{}])[0]
    thumb = info.get("thumburl") or info.get("url") or ""
    if not re.search(r"\.(jpe?g|png)$", thumb, re.I) or (info.get("width") or 0) < MIN_WIDTH:
        return None  # Threads берёт только JPEG и PNG
    meta = info.get("extmetadata") or {}
    value = lambda k: _plain((meta.get(k) or {}).get("value", ""))
    title = re.sub(r"^File:|\.\w+$", "", page.get("title", ""))
    return {
        "url": thumb,
        "preview": thumb.replace(f"/{WIDTH}px-", f"/{PREVIEW}px-"),
        "page": info.get("descriptionurl", ""),
        "title": title.replace("_", " "),
        "author": value("Artist")[:120],
        "license": value("LicenseShortName") or "Wikimedia Commons",
        "attribution": value("AttributionRequired").lower() == "true",
    }


def search(query: str, limit: int = 10) -> list[dict]:
    r = requests.get(API, headers={"User-Agent": UA}, timeout=20, params={
        "action": "query", "format": "json", "formatversion": "2",
        "generator": "search", "gsrnamespace": "6", "gsrlimit": str(limit),
        "gsrsearch": f"{query} filetype:bitmap",
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": str(WIDTH),
        "iiextmetadatafilter": "Artist|LicenseShortName|AttributionRequired",
    })
    r.raise_for_status()
    pages = sorted((r.json().get("query") or {}).get("pages") or [], key=lambda p: p.get("index", 0))
    return [img for img in map(_image, pages) if img]


def find(queries: list[str], want: int = OPTIONS) -> list[dict]:
    """Варианты картинок по запросам ИИ, от самого точного запроса к общему. Без сети — пустой список."""
    found, seen = [], set()
    for q in queries[:3]:
        if not q.strip() or len(found) >= want:
            continue
        try:
            results = search(q.strip())
        except Exception as e:  # нет сети, Commons недоступен: пост выйдет без картинки
            print(f"Не удалось найти картинку «{q}»: {e}", file=sys.stderr)
            continue
        for img in results:
            if img["page"] not in seen:
                seen.add(img["page"])
                found.append(img)
    return found[:want]


def chosen(story: dict) -> dict | None:
    """Картинка, выбранная в черновике (поле image — номер варианта или None)."""
    i, options = story.get("image"), story.get("images") or []
    return options[i] if isinstance(i, int) and 0 <= i < len(options) else None


def credit(img: dict) -> str:
    """Подпись для лицензий, которые требуют указать автора; для общественного достояния пусто."""
    if not img.get("attribution"):
        return ""
    who = f"{img['author']}, " if img.get("author") else ""
    return f"🖼 {who}{img['license']}, Wikimedia Commons"
