"""Картинка к первому посту. Два источника:

- Wikimedia Commons: архивные фото, картины, гравюры, карты. Там только свободные файлы (общественное достояние
  или открытые лицензии); для лицензий, которые требуют указать автора, бот добавляет подпись в конец цепочки.
- Статья-источник: главная картинка страницы (og:image), та же, что видна в превью ссылки. Подходит для новостей
  и свежих тем, которых нет на Commons. Права на неё у издания, поэтому бот всегда подписывает сайт.

В креативном режиме аккаунта картинку не ищут, а рисуют: бесплатный генератор Pollinations.ai (без ключа и
регистрации) рисует по описанию от ИИ, и картинка доступна по ссылке, как и найденные.

Threads сам скачивает картинку по ссылке, поэтому хранить файлы у себя не нужно.
"""
import html
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode, urljoin, urlparse

import requests

API = "https://commons.wikimedia.org/w/api.php"
UA = "HistorianBot/1.0 (https://github.com/fibin/historician)"  # Wikimedia просит представляться
WIDTH = 1280      # стандартный размер миниатюр Commons; Threads принимает до 1440 по ширине
PREVIEW = 330     # маленькая копия для окна
MIN_WIDTH = 500   # мельче выглядит плохо
OPTIONS = 6       # сколько вариантов показывать в окне
MAX_BYTES = 8 * 1024 * 1024  # больше Threads не принимает
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/129.0 Safari/537.36")  # многие сайты не отдают страницу «ботам»
# Откуда брать картинку: значение настройки аккаунта → источники по порядку
SOURCES = {
    "commons+article": ("commons", "article"),
    "article+commons": ("article", "commons"),
    "commons": ("commons",),
    "article": ("article",),
}
DEFAULT_SOURCE = "commons+article"


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
    return find_explained(queries, want)[0]


def find_explained(queries: list[str], want: int = OPTIONS) -> tuple[list[dict], str]:
    """То же, что find, плюс объяснение для окна, если ничего не нашлось."""
    queries = [q.strip() for q in queries if q and q.strip()]
    if not queries:
        return [], "ИИ не подсказал, что искать."
    found, seen, errors = [], set(), []
    for q in queries[:4]:
        if len(found) >= want:
            break
        try:
            results = search(q)
        except Exception as e:  # нет сети, Commons недоступен: пост выйдет без картинки
            print(f"Не удалось найти картинку «{q}»: {e}", file=sys.stderr)
            errors.append(str(e))
            continue
        for img in results:
            if img["page"] not in seen:
                seen.add(img["page"])
                found.append(img)
    if found:
        return found[:want], ""
    if errors and len(errors) == len(queries[:4]):
        return [], f"Wikimedia Commons не ответил: {errors[-1][:200]}"
    return [], "На Wikimedia Commons ничего не нашлось по запросам: " + "; ".join(queries[:4])


def _meta_image(page_html: str) -> tuple[str, str]:
    """Главная картинка и заголовок страницы из тегов og:/twitter:."""
    found: dict[str, str] = {}
    for tag in re.findall(r"<meta\b[^>]*>", page_html[:500_000], re.I):
        attrs = dict((k.lower(), html.unescape(v1 or v2)) for k, v1, v2 in
                     re.findall(r'([\w:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', tag))
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key and attrs.get("content") and key not in found:
            found[key] = attrs["content"].strip()
    image = next((found[k] for k in ("og:image:secure_url", "og:image", "og:image:url", "twitter:image",
                                     "twitter:image:src") if found.get(k)), "")
    return image, found.get("og:title") or found.get("twitter:title") or ""


def _usable(url: str) -> bool:
    """Threads берёт JPEG и PNG до 8 МБ: проверяем, что по ссылке именно такая картинка."""
    try:
        with requests.get(url, headers={"User-Agent": BROWSER_UA, "Accept": "image/jpeg,image/png;q=0.9,*/*;q=0.1"},
                          timeout=15, stream=True) as r:
            kind = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
            size = int(r.headers.get("Content-Length") or 0)
            return r.status_code == 200 and kind in ("image/jpeg", "image/png") and size <= MAX_BYTES
    except Exception:
        return False


def from_article(page_url: str) -> dict | None:
    """Главная картинка статьи или None, если её нет или Threads её не примет."""
    try:
        r = requests.get(page_url, headers={"User-Agent": BROWSER_UA, "Accept-Language": "uk,ru;q=0.8,en;q=0.6"},
                         timeout=20)
        r.raise_for_status()
    except Exception as e:
        print(f"Не удалось открыть статью {page_url}: {e}", file=sys.stderr)
        return None
    image, title = _meta_image(r.text)
    if not image:
        return None
    image = urljoin(r.url, image)
    if not image.startswith("https://") or not _usable(image):
        return None
    site = urlparse(r.url).netloc.removeprefix("www.")
    return {"url": image, "preview": image, "page": page_url, "title": title[:150] or site, "author": site,
            "license": "", "attribution": True, "source": "article"}


def from_articles(urls: list[str], want: int = OPTIONS) -> list[dict]:
    found = []
    for url in urls[:4]:
        if len(found) >= want:
            break
        img = from_article(url) if url.startswith("http") else None
        if img and img["url"] not in {i["url"] for i in found}:
            found.append(img)
    return found


def collect(queries: list[str], article_urls: list[str], source: str = DEFAULT_SOURCE) -> tuple[list[dict], str]:
    """Варианты картинок из выбранных источников по порядку и объяснение, если ничего не нашлось."""
    found, notes = [], []
    for kind in SOURCES.get(source, SOURCES[DEFAULT_SOURCE]):
        if kind == "commons":
            imgs, note = find_explained(queries)
        else:
            imgs = from_articles(article_urls)
            note = "" if imgs else "В статьях-источниках нет картинки, которую примет Threads (нужен JPEG или PNG)."
        found += [i for i in imgs if i["url"] not in {f["url"] for f in found}]
        if note:
            notes.append(note)
    return found[:OPTIONS], ("" if found else " ".join(notes))


GENERATOR = "https://image.pollinations.ai/prompt/"
GEN_SIZE = (1080, 1350)  # 4:5, так Threads показывает картинку крупнее всего
GEN_OPTIONS = 3
GEN_TIMEOUT = 150        # генератор рисует до пары минут, особенно когда занят


def generate_url(prompt: str, seed: int) -> str:
    w, h = GEN_SIZE
    params = urlencode({"width": w, "height": h, "seed": seed, "nologo": "true", "model": "flux"})
    return f"{GENERATOR}{quote(prompt.strip()[:600], safe='')}?{params}"


def _draw(prompt: str, seed: int) -> dict | None:
    """Рисует картинку и проверяет, что она готова: генератор запоминает её, и Threads потом получит ту же."""
    url = generate_url(prompt, seed)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=GEN_TIMEOUT)
        kind = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if r.status_code != 200 or kind not in ("image/jpeg", "image/png") or len(r.content) > MAX_BYTES:
            raise RuntimeError(f"ответ {r.status_code} {kind}")
    except Exception as e:
        print(f"Не удалось нарисовать картинку «{prompt[:80]}»: {e}", file=sys.stderr)
        return None
    return {"url": url, "preview": url, "page": url, "title": prompt.strip()[:150], "author": "",
            "license": "", "attribution": False, "source": "generated"}


def generated(prompts: list[str], want: int = GEN_OPTIONS) -> tuple[list[dict], str]:
    """Варианты нарисованной картинки по описаниям от ИИ (по кругу, с разными seed) и объяснение, если не вышло."""
    prompts = [p.strip() for p in prompts if p and p.strip()]
    if not prompts:
        return [], "ИИ не описал картинку."
    jobs = [(prompts[i % len(prompts)], random.randint(1, 10**9)) for i in range(want)]
    with ThreadPoolExecutor(max_workers=want) as pool:
        found = [img for img in pool.map(lambda job: _draw(*job), jobs) if img]
    return found, ("" if found else "Генератор картинок Pollinations.ai сейчас не ответил. "
                                    "Попробуйте ещё раз кнопкой или опубликуйте без картинки.")


def chosen(story: dict) -> dict | None:
    """Картинка, выбранная в черновике (поле image — номер варианта или None)."""
    i, options = story.get("image"), story.get("images") or []
    return options[i] if isinstance(i, int) and 0 <= i < len(options) else None


def credit(img: dict) -> str:
    """Подпись для лицензий, которые требуют указать автора; для общественного достояния пусто."""
    if not img.get("attribution"):
        return ""
    if img.get("source") == "article":
        return f"🖼 {img['author']}"
    who = f"{img['author']}, " if img.get("author") else ""
    return f"🖼 {who}{img['license']}, Wikimedia Commons"
