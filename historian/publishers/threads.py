"""Публикация в Threads через Threads API (graph.threads.net)."""
import time

import requests

from ..config import ThreadsCredentials

BASE = "https://graph.threads.net/v1.0"


def _post(url: str, params: dict) -> dict:
    r = requests.post(url, params=params, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Threads API {r.status_code}: {r.text}")
    return r.json()


def post_thread(creds: ThreadsCredentials, parts: list[str]) -> list[str]:
    ids: list[str] = []
    for text in parts:
        params = {"media_type": "TEXT", "text": text, "access_token": creds.access_token}
        if ids:
            params["reply_to_id"] = ids[-1]
        container = _post(f"{BASE}/{creds.user_id}/threads", params)["id"]
        # Meta рекомендует подождать, пока контейнер обработается, перед публикацией.
        time.sleep(5)
        published = _post(f"{BASE}/{creds.user_id}/threads_publish",
                           {"creation_id": container, "access_token": creds.access_token})
        ids.append(published["id"])
    return ids


def refresh_token(access_token: str) -> dict:
    """Продлевает долгоживущий токен (живёт 60 дней). Возвращает access_token и expires_in."""
    r = requests.get(f"{BASE.rsplit('/', 1)[0]}/refresh_access_token",
                     params={"grant_type": "th_refresh_token", "access_token": access_token},
                     timeout=30)
    r.raise_for_status()
    return r.json()
