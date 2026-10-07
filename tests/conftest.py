import pytest

from historian import accounts, images, web
from historian.publishers import threads as threads_pub


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Каждый тест в пустой папке: свои accounts/, data/, out/ и никаких ключей из окружения."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(accounts, "ROOT", str(tmp_path / "accounts"))
    for k in ("THREADS_USER_ID", "THREADS_ACCESS_TOKEN", "THREADS_USERNAME", "HISTORIAN_ENGINE", "HISTORIAN_PUBLISH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(threads_pub, "permalink", lambda creds, post_id: f"https://www.threads.net/@x/post/{post_id}")
    monkeypatch.setattr(threads_pub, "followers", lambda creds: 0)
    monkeypatch.setattr(threads_pub, "post_insights", lambda creds, post_id: {})
    monkeypatch.setattr(images, "search", lambda query, limit=10: [])
    monkeypatch.setattr(images, "from_article", lambda url: None)
    monkeypatch.setattr(threads_pub, "conversation", lambda creds, post_id, pages=5: [])
    # фоновые обновления статистики и комментариев в тестах не запускаем: они переживают тест и его папку
    monkeypatch.setattr(web, "_in_background", lambda fn, *args: None)
    web.jobs.clear()
    web.stats_running.clear()
    web.comments_running.clear()
    return tmp_path
