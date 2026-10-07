import os
from dataclasses import dataclass

MODEL = os.environ.get("HISTORIAN_MODEL", "claude-opus-5-5")
LANGUAGE = os.environ.get("HISTORIAN_LANGUAGE", "українська")
HISTORY_PATH = os.environ.get("HISTORIAN_HISTORY", "data/history.json")

THREADS_LIMIT = 500


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ThreadsCredentials:
    user_id: str
    access_token: str

    @classmethod
    def from_env(cls) -> "ThreadsCredentials | None":
        uid, tok = os.environ.get("THREADS_USER_ID"), os.environ.get("THREADS_ACCESS_TOKEN")
        return cls(uid, tok) if uid and tok else None
