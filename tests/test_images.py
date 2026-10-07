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
