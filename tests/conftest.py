import pytest

from historian import accounts, web
from historian.publishers import threads as threads_pub


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Каждый тест в пустой папке: свои accounts/, data/, out/ и никаких ключей из окружения."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(accounts, "ROOT", str(tmp_path / "accounts"))
    for k in ("THREADS_USER_ID", "THREADS_ACCESS_TOKEN", "THREADS_USERNAME", "HISTORIAN_ENGINE", "HISTORIAN_PUBLISH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(threads_pub, "permalink", lambda creds, post_id: f"https://www.threads.net/@x/post/{post_id}")
    web.jobs.clear()
    return tmp_path
