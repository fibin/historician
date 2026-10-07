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


def whoami(access_token: str) -> dict:
    """id и username аккаунта, которому принадлежит токен."""
    r = requests.get(f"{BASE}/me", params={"fields": "id,username", "access_token": access_token},
                     timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Threads API {r.status_code}: {r.text}")
    return r.json()


def permalink(creds: ThreadsCredentials, post_id: str) -> str | None:
    r = requests.get(f"{BASE}/{post_id}", params={"fields": "permalink", "access_token": creds.access_token},
                     timeout=30)
    return r.json().get("permalink") if r.ok else None


# Статистика. Нужно разрешение threads_manage_insights в приложении Meta и токен, полученный после его добавления.
POST_METRICS = ("views", "likes", "replies", "reposts", "quotes", "shares")


class NoPermission(RuntimeError):
    """У токена нет нужного разрешения: надо добавить его в приложении Meta и получить новый токен."""


def _get(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=30)
    if r.status_code >= 300:
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {}
        code = err.get("code")
        if code == 10 or (isinstance(code, int) and 200 <= code < 300) or "permission" in str(err.get("message", "")).lower():
            raise NoPermission(err.get("message") or r.text)
        raise RuntimeError(f"Threads API {r.status_code}: {r.text}")
    return r.json()


def _value(metric: dict) -> int:
    if "total_value" in metric:
        return int(metric["total_value"].get("value") or 0)
    values = metric.get("values") or [{}]
    return int(values[-1].get("value") or 0)


def post_insights(creds: ThreadsCredentials, post_id: str) -> dict:
    """Просмотры, лайки, ответы, репосты, цитаты и пересылки поста."""
    data = _get(f"{BASE}/{post_id}/insights",
                {"metric": ",".join(POST_METRICS), "access_token": creds.access_token})["data"]
    return {m["name"]: _value(m) for m in data}


def followers(creds: ThreadsCredentials) -> int:
    data = _get(f"{BASE}/{creds.user_id}/threads_insights",
                {"metric": "followers_count", "access_token": creds.access_token})["data"]
    return _value(data[0]) if data else 0
