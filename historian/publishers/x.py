"""Публикация треда в X через API v2 (OAuth 1.0a, контекст пользователя)."""
from requests_oauthlib import OAuth1Session

from ..config import XCredentials

TWEETS_URL = "https://api.x.com/2/tweets"


def post_thread(creds: XCredentials, parts: list[str]) -> list[str]:
    session = OAuth1Session(creds.api_key, creds.api_secret,
                            creds.access_token, creds.access_secret)
    ids: list[str] = []
    for text in parts:
        payload = {"text": text}
        if ids:
            payload["reply"] = {"in_reply_to_tweet_id": ids[-1]}
        r = session.post(TWEETS_URL, json=payload, timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"X API {r.status_code}: {r.text}")
        ids.append(r.json()["data"]["id"])
    return ids
