import os
from dataclasses import dataclass

MODEL = os.environ.get("HISTORIAN_MODEL", "claude-opus-5-5")
LANGUAGE = os.environ.get("HISTORIAN_LANGUAGE", "українська")
HISTORY_PATH = os.environ.get("HISTORIAN_HISTORY", "data/history.json")

X_LIMIT = 280
THREADS_LIMIT = 500


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class XCredentials:
    api_key: str
    api_secret: str
    access_token: str
    access_secret: str

    @classmethod
    def from_env(cls) -> "XCredentials | None":
        vals = [os.environ.get(k) for k in
                ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")]
        return cls(*vals) if all(vals) else None


@dataclass
class ThreadsCredentials:
    user_id: str
    access_token: str

    @classmethod
    def from_env(cls) -> "ThreadsCredentials | None":
        uid, tok = os.environ.get("THREADS_USER_ID"), os.environ.get("THREADS_ACCESS_TOKEN")
        return cls(uid, tok) if uid and tok else None
