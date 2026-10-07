from historian import images, main
from historian.publishers import threads as threads_pub

REAL_SEARCH = images.search

PAGE = {
    "title": "File:Tycho Brahe by Eduard Ender.jpg", "index": 2,
    "imageinfo": [{
        "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/T.jpg/1280px-T.jpg",
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/T.jpg",
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:T.jpg", "width": 2000, "mime": "image/jpeg",
        "extmetadata": {"Artist": {"value": '<a href="//x">Eduard Ender</a>'},
                        "LicenseShortName": {"value": "CC BY-SA 4.0"}, "AttributionRequired": {"value": "true"}},
    }],
}


class FakeResp:
    def __init__(self, data, status_code=200):
        self._data, self.status_code, self.text = data, status_code, str(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


def test_search_keeps_large_jpeg_and_png_and_reads_license(monkeypatch):
    monkeypatch.setattr(images, "search", REAL_SEARCH)  # conftest подменяет поиск, здесь нужен настоящий
    small = {"title": "File:Small.png", "index": 1, "imageinfo": [{"thumburl": "https://u/s.png", "width": 200}]}
    webp = {"title": "File:Map.svg", "index": 0, "imageinfo": [{"thumburl": "https://u/1280px-m.webp", "width": 3000}]}
    seen = {}

    def get(url, headers, timeout, params):
        seen.update(params, ua=headers["User-Agent"])
        return FakeResp({"query": {"pages": [PAGE, webp, small]}})
    monkeypatch.setattr(images.requests, "get", get)
    [img] = images.search("Tycho Brahe portrait")
    assert seen["gsrsearch"] == "Tycho Brahe portrait filetype:bitmap" and "HistorianBot" in seen["ua"]
    assert img["url"].endswith("1280px-T.jpg") and img["preview"].endswith("330px-T.jpg")
    assert (img["author"], img["license"], img["attribution"]) == ("Eduard Ender", "CC BY-SA 4.0", True)
    assert img["title"] == "Tycho Brahe by Eduard Ender"
    assert images.credit(img) == "🖼 Eduard Ender, CC BY-SA 4.0, Wikimedia Commons"
    assert images.credit({**img, "attribution": False}) == ""


def test_find_dedups_and_survives_network_errors(monkeypatch):
    img = {"page": "p1", "url": "u"}

    def search(q, limit=10):
        if q == "bad":
            raise OSError("offline")
        return [img, {"page": q, "url": "u"}]
    monkeypatch.setattr(images, "search", search)
    assert [i["page"] for i in images.find(["bad", "a", "b"])] == ["p1", "a", "b"]
    assert images.find([]) == []


def test_generate_attaches_images_unless_disabled(monkeypatch):
    from historian import engines
    monkeypatch.setattr(engines, "generate_story", lambda *a, **k: {
        "subject": "X", "topic": "t", "threads_posts": ["p"], "sources": [], "image_queries": ["q"]})
    monkeypatch.setattr(images, "search", lambda q, limit=10: [{"page": "p", "url": "https://u/1280px-a.jpg"}])
    story = main.generate("claude-code", [], "тема")
    assert story["image"] == 0 and story["images"][0]["page"] == "p"
    assert "images" not in main.generate("claude-code", [], "тема", with_image=False)


def test_publish_sends_image_and_credit(monkeypatch):
    sent = {}
    monkeypatch.setattr(threads_pub, "post_thread",
                        lambda creds, parts, image_url=None: sent.update(parts=parts, image=image_url) or ["1"])
    img = {"url": "https://u/1280px-a.jpg", "page": "https://c/File:a", "author": "A", "license": "CC BY 4.0",
           "attribution": True}
    story = {"threads_posts": ["Перший", "Останній"], "images": [img], "image": 0}
    posted = main.publish(story, threads_pub.ThreadsCredentials("u", "t"))
    assert sent["image"] == img["url"] and posted["image"] == img["page"]
    assert sent["parts"][-1].endswith("🖼 A, CC BY 4.0, Wikimedia Commons")
    main.publish({**story, "image": None}, threads_pub.ThreadsCredentials("u", "t"))
    assert sent["image"] is None and sent["parts"] == ["Перший", "Останній"]


def _threads_api(monkeypatch, status):
    calls = []

    def post(url, params, timeout):
        calls.append(dict(params, endpoint=url.rsplit("/", 1)[-1]))
        return FakeResp({"id": f"id{len(calls)}"})
    monkeypatch.setattr(threads_pub.requests, "post", post)
    monkeypatch.setattr(threads_pub.requests, "get", lambda url, params, timeout: FakeResp({"status": status}))
    monkeypatch.setattr(threads_pub.time, "sleep", lambda s: None)
    return calls


def test_image_goes_with_first_post(monkeypatch):
    calls = _threads_api(monkeypatch, "FINISHED")
    threads_pub.post_thread(threads_pub.ThreadsCredentials("u", "t"), ["one", "two"], image_url="https://u/a.jpg")
    assert calls[0]["media_type"] == "IMAGE" and calls[0]["image_url"] == "https://u/a.jpg"
    assert calls[2]["media_type"] == "TEXT" and "image_url" not in calls[2]


def test_rejected_image_falls_back_to_text(monkeypatch):
    calls = _threads_api(monkeypatch, "ERROR")
    ids = threads_pub.post_thread(threads_pub.ThreadsCredentials("u", "t"), ["one"], image_url="https://u/a.jpg")
    assert [c["media_type"] for c in calls if c["endpoint"] == "threads"] == ["IMAGE", "TEXT"]
    assert calls[-1]["creation_id"] == "id2" and len(ids) == 1


def test_find_explains_why_nothing_was_found(monkeypatch):
    monkeypatch.setattr(images, "search", lambda q, limit=10: [])
    assert images.find_explained([" ", ""]) == ([], "ИИ не подсказал, что искать.")
    assert "ничего не нашлось по запросам: moose; Tycho" in images.find_explained(["moose", "Tycho"])[1]

    def offline(q, limit=10):
        raise OSError("403 Forbidden")
    monkeypatch.setattr(images, "search", offline)
    assert images.find_explained(["moose"])[1] == "Wikimedia Commons не ответил: 403 Forbidden"


def test_subject_is_the_last_resort_query(monkeypatch):
    asked = []
    monkeypatch.setattr(images, "search", lambda q, limit=10: asked.append(q) or ([{"page": q, "url": "u"}] if q == "Тихо Браге" else []))
    story = main.add_images({"subject": "Тихо Браге", "image_queries": ["moose beer castle"]})
    assert asked == ["moose beer castle", "Тихо Браге"] and story["image"] == 0 and story["image_note"] == ""


def test_window_can_search_again_for_an_old_draft(monkeypatch):
    from historian import accounts, web
    acc = accounts.ensure()[0]
    draft = main.save_draft({"subject": "Тихо Браге", "topic": "t", "threads_posts": ["p"], "sources": []}, acc.out_dir)
    monkeypatch.setattr(images, "search", lambda q, limit=10: [{"page": "p1", "url": "https://u/1.jpg"}])
    r = web.find_image(acc.id)
    assert r["image"] == 0 and r["images"][0]["page"] == "p1"
    import json
    assert json.load(open(draft, encoding="utf-8"))["images"][0]["page"] == "p1"


REAL_FROM_ARTICLE = images.from_article  # conftest подменяет его заглушкой

PAGE_HTML = """<html><head>
<meta name="twitter:image" content="https://cdn.example.com/tw.jpg">
<meta content="/img/lead.jpg?w=1200&amp;q=80" property="og:image" />
<meta property='og:title' content='ChatGPT for Teens: &quot;звіт&quot;'>
</head></html>"""


class _Page:
    def __init__(self, text="", headers=None, status=200, url="https://www.example.com/news/1"):
        self.text, self.headers, self.status_code, self.url = text, headers or {}, status, url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(self.status_code)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_meta_image_prefers_og_and_unescapes():
    assert images._meta_image(PAGE_HTML) == ("/img/lead.jpg?w=1200&q=80", 'ChatGPT for Teens: "звіт"')
    assert images._meta_image("<meta name='twitter:image' content='https://x/y.png'>") == ("https://x/y.png", "")


def test_article_image_is_checked_and_credited(monkeypatch):
    monkeypatch.setattr(images, "from_article", REAL_FROM_ARTICLE)
    kinds = {"https://www.example.com/img/lead.jpg?w=1200&q=80": "image/jpeg"}

    def get(url, headers, timeout, stream=False):
        if url.startswith("https://www.example.com/news"):
            return _Page(PAGE_HTML)
        return _Page(headers={"Content-Type": kinds.get(url, "image/webp"), "Content-Length": "200000"})
    monkeypatch.setattr(images.requests, "get", get)
    img = images.from_article("https://www.example.com/news/1")
    assert img["url"] == "https://www.example.com/img/lead.jpg?w=1200&q=80"
    assert (img["author"], img["source"], img["page"]) == ("example.com", "article", "https://www.example.com/news/1")
    assert images.credit(img) == "🖼 example.com"
    kinds.clear()  # сайт отдаёт только webp: Threads не примет
    assert images.from_article("https://www.example.com/news/1") is None


def test_collect_follows_account_order(monkeypatch):
    commons = {"url": "c.jpg", "page": "c"}
    article = {"url": "a.jpg", "page": "a", "source": "article"}
    monkeypatch.setattr(images, "search", lambda q, limit=10: [commons])
    monkeypatch.setattr(images, "from_article", lambda url: article)
    assert [i["url"] for i in images.collect(["q"], ["https://s"], "article+commons")[0]] == ["a.jpg", "c.jpg"]
    assert [i["url"] for i in images.collect(["q"], ["https://s"], "commons")[0]] == ["c.jpg"]
    monkeypatch.setattr(images, "search", lambda q, limit=10: [])
    monkeypatch.setattr(images, "from_article", lambda url: None)
    found, note = images.collect(["q"], ["https://s"], "commons+article")
    assert found == [] and "ничего не нашлось" in note and "JPEG или PNG" in note
