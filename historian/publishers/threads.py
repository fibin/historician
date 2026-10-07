"""Публикация в Threads через Threads API (graph.threads.net)."""
import sys
import time

import requests

from ..config import ThreadsCredentials

BASE = "https://graph.threads.net/v1.0"


def _post(url: str, params: dict) -> dict:
    return _check(requests.post(url, params=params, timeout=30))


def _container(creds: ThreadsCredentials, text: str, reply_to: str | None, image_url: str | None) -> str:
    params = {"media_type": "TEXT", "text": text, "access_token": creds.access_token}
    if image_url:
        params.update(media_type="IMAGE", image_url=image_url)
    if reply_to:
        params["reply_to_id"] = reply_to
    return _post(f"{BASE}/{creds.user_id}/threads", params)["id"]


def _wait_ready(creds: ThreadsCredentials, container: str, timeout: int = 60) -> None:
    """Картинку Threads скачивает и обрабатывает сам: ждём, пока контейнер будет готов."""
    deadline = time.monotonic() + timeout
    while True:
        st = _get(f"{BASE}/{container}", {"fields": "status,error_message", "access_token": creds.access_token})
        if st.get("status") == "FINISHED":
            return
        if st.get("status") in ("ERROR", "EXPIRED") or time.monotonic() > deadline:
            raise RuntimeError(f"Threads не принял картинку: {st.get('error_message') or st.get('status')}")
        time.sleep(3)


def post_thread(creds: ThreadsCredentials, parts: list[str], image_url: str | None = None) -> list[str]:
    """Публикует цепочку. Картинка (если есть) идёт с первым постом; если Threads её не принял,
    первый пост выходит без картинки, чтобы публикация не сорвалась."""
    ids: list[str] = []
    for i, text in enumerate(parts):
        reply_to = ids[-1] if ids else None
        container = None
        if i == 0 and image_url:
            try:
                container = _container(creds, text, reply_to, image_url)
                _wait_ready(creds, container)
            except Exception as e:
                print(f"Картинка не прикрепилась, публикую без неё: {e}", file=sys.stderr)
                container = None
        if container is None:
            container = _container(creds, text, reply_to, None)
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
    return _check(requests.get(url, params=params, timeout=30))


def _check(r) -> dict:
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


# Комментарии. Нужны разрешения threads_read_replies (читать) и threads_manage_replies (отвечать).
def conversation(creds: ThreadsCredentials, post_id: str, pages: int = 5) -> list[dict]:
    """Все ответы под постом на любой глубине, включая продолжения нашей цепочки."""
    params = {"fields": "id,text,username,timestamp,replied_to,hide_status", "reverse": "false",
              "access_token": creds.access_token}
    url, out = f"{BASE}/{post_id}/conversation", []
    for _ in range(pages):
        data = _get(url, params)
        out += data.get("data", [])
        url = (data.get("paging") or {}).get("next")
        if not url:
            break
        params = {}  # в ссылке next параметры уже есть
    return out


def reply(creds: ThreadsCredentials, comment_id: str, text: str) -> str:
    """Ответ на комментарий от имени аккаунта. Возвращает id ответа."""
    container = _container(creds, text, comment_id, None)
    time.sleep(5)
    return _post(f"{BASE}/{creds.user_id}/threads_publish",
                 {"creation_id": container, "access_token": creds.access_token})["id"]
