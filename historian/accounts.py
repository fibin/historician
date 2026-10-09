"""Аккаунты Threads. У каждого своя тема, язык, ИИ, время публикации, журнал и черновики.
Тема («О чём аккаунт») решает, какой материал ищет ИИ и как пишет посты.

Всё лежит в папке accounts/ (в git не попадает, там токены):
    accounts/<id>/account.json   настройки и токен
    accounts/<id>/history.json   что уже публиковалось в этом аккаунте
    accounts/<id>/state.json     попытки автопубликации за сегодня
    accounts/<id>/out/           черновики
"""
import glob
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timedelta

from . import history
from .config import HISTORY_PATH, LANGUAGE, ThreadsCredentials, env_flag

ROOT = os.environ.get("HISTORIAN_ACCOUNTS", "accounts")
# Тема, с которой начинался бот: её получает аккаунт, перенесённый из старых настроек.
HISTORY_THEME = (
    "Малоизвестные истории о реальных людях любых эпох и стран: привычки, причуды, бытовые детали, "
    "странные эпизоды из мемуаров, дневников и писем современников, слуг, секретарей, врачей, родственников.\n"
    "Не общеизвестные факты и не популярные сюжеты вроде «Гитлер хотел стать художником» или "
    "«Наполеон был низкого роста», а то, что надо специально искать. Не зацикливаться на диктаторах и монархах: "
    "учёные, художники, путешественники, врачи, инженеры, авантюристы тоже подходят. "
    "Если что-то известно со слов одного мемуариста, так и сказать."
)
# Так выглядела тема по умолчанию в прошлой версии; такие аккаунты получают подробную HISTORY_THEME.
_OLD_DEFAULT_THEME = ("малоизвестные истории о реальных людях любых эпох и стран: привычки, причуды, "
                      "эпизоды из мемуаров, дневников и писем современников")
TOKEN_REFRESH_DAYS = 7   # продлеваем токен раз в неделю, он живёт 60 дней
TOKEN_LIFETIME_DAYS = 60


@dataclass
class Account:
    id: str
    name: str
    theme: str = ""
    language: str = LANGUAGE
    engine: str = "claude-code"
    post_time: str = "10:00"
    auto_publish: bool = False
    with_image: bool = True   # подбирать картинку к первому посту
    image_source: str = "commons+article"  # откуда: см. images.SOURCES
    creative: bool = False    # придумывать свои истории вместо поиска реальных с источниками
    posts_min: int = 1        # сколько постов в цепочке: от и до
    posts_max: int = 10
    threads_user_id: str = ""
    threads_token: str = ""
    threads_username: str = ""
    token_date: str = ""      # когда токен сохранён или продлён
    token_expires: str = ""
    token_checked: str = ""   # последняя попытка продления, чтобы не стучаться чаще раза в день
    created: str = ""

    @property
    def folder(self) -> str:
        return os.path.join(ROOT, self.id)

    @property
    def history_path(self) -> str:
        return os.path.join(self.folder, "history.json")

    @property
    def out_dir(self) -> str:
        return os.path.join(self.folder, "out")

    def creds(self) -> ThreadsCredentials | None:
        if self.threads_user_id and self.threads_token:
            return ThreadsCredentials(self.threads_user_id, self.threads_token)
        return None

    def history(self) -> list[dict]:
        return history.load(self.history_path)

    def save(self) -> None:
        _write_json(os.path.join(self.folder, "account.json"), asdict(self))

    def public(self) -> dict:
        """Для окна: всё, кроме токена."""
        data = asdict(self)
        data.pop("threads_token")
        return {**data, "has_token": bool(self.threads_token)}


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _load(path: str) -> Account:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    names = {f.name for f in fields(Account)}
    acc = Account(**{k: v for k, v in data.items() if k in names})
    if acc.theme == _OLD_DEFAULT_THEME:
        acc.theme = HISTORY_THEME
    return acc


def list_all() -> list[Account]:
    found = [_load(p) for p in glob.glob(os.path.join(ROOT, "*", "account.json"))
             if not os.path.basename(os.path.dirname(p)).startswith("_")]
    return sorted(found, key=lambda a: (a.created, a.id))


def get(account_id: str) -> Account:
    path = os.path.join(ROOT, account_id, "account.json")
    if not re.fullmatch(r"[a-z0-9-]+", account_id or "") or not os.path.exists(path):
        raise ValueError(f"Нет такого аккаунта: {account_id}")
    return _load(path)


# Для имени папки: «Морські пригоди» → morski-pryhody
TRANSLIT = dict(zip("абвгґдеєёжзиіїйклмнопрстуфхцчшщъыьэюя", [
    "a", "b", "v", "h", "g", "d", "e", "ie", "io", "zh", "z", "y", "i", "i", "i", "k", "l", "m", "n", "o", "p",
    "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "", "y", "", "e", "iu", "ia"]))


def _now() -> str:
    return datetime.now().isoformat()  # с микросекундами: по нему упорядочены вкладки


def create(name: str, **settings) -> Account:
    name = name.strip() or "Новый аккаунт"
    latin = "".join(TRANSLIT.get(ch, ch) for ch in name.lower())
    base = re.sub(r"[^a-z0-9]+", "-", latin).strip("-")[:30] or "account"
    taken = {a.id for a in list_all()} | {"main"}
    acc_id, n = base, 2
    while acc_id in taken or os.path.exists(os.path.join(ROOT, acc_id)):
        acc_id, n = f"{base}-{n}", n + 1
    acc = Account(id=acc_id, name=name, created=_now(), **settings)
    acc.save()
    return acc


def delete(account_id: str) -> None:
    """Не стираем, а убираем в accounts/_deleted: там остаются журнал и черновики."""
    acc = get(account_id)
    trash = os.path.join(ROOT, "_deleted", f"{acc.id}-{datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(os.path.dirname(trash), exist_ok=True)
    shutil.move(acc.folder, trash)


def migrate_legacy() -> Account:
    """Первый запуск после обновления: аккаунт из .env, журнал data/history.json и черновики out/
    переезжают в accounts/main. Старые файлы не трогаем."""
    from .engines import ENGINES

    env = os.environ
    engine = env.get("HISTORIAN_ENGINE", "claude-code")
    acc = Account(
        id="main", name="Основной", created=_now(), theme=HISTORY_THEME,
        engine=engine if engine in ENGINES else "claude-code",
        auto_publish=env_flag("HISTORIAN_PUBLISH"),
        threads_user_id=env.get("THREADS_USER_ID", ""),
        threads_token=env.get("THREADS_ACCESS_TOKEN", ""),
        threads_username=env.get("THREADS_USERNAME", ""),
    )
    os.makedirs(acc.out_dir, exist_ok=True)
    if os.path.exists(HISTORY_PATH):
        shutil.copyfile(HISTORY_PATH, acc.history_path)
    for draft in glob.glob(os.path.join("out", "*.json")):
        shutil.copy2(draft, acc.out_dir)
    acc.save()
    return acc


def ensure() -> list[Account]:
    """Все аккаунты; если их ещё нет, создаёт первый из старых настроек."""
    return list_all() or [migrate_legacy()]


def set_token(acc: Account, user_id: str, token: str, username: str, today: date | None = None) -> None:
    today = today or date.today()
    acc.threads_user_id, acc.threads_token, acc.threads_username = user_id, token, username
    acc.token_date = today.isoformat()
    acc.token_expires = (today + timedelta(days=TOKEN_LIFETIME_DAYS)).isoformat()
    acc.token_checked = ""


def refresh_token_if_needed(acc: Account, today: date | None = None, force: bool = False) -> bool:
    """Продлевает токен Threads, если он не продлевался неделю. Не чаще одной попытки в день."""
    from .publishers import threads as threads_pub

    if not acc.threads_token:
        return False
    today = today or date.today()
    if not force:
        if acc.token_checked == today.isoformat():
            return False
        if acc.token_date and (today - date.fromisoformat(acc.token_date)).days < TOKEN_REFRESH_DAYS:
            return False
    acc.token_checked = today.isoformat()
    try:
        fresh = threads_pub.refresh_token(acc.threads_token)
    except Exception as e:  # токен моложе суток, сеть, истёкший токен: попробуем завтра
        print(f"[{acc.name}] не удалось продлить токен Threads: {e}", file=sys.stderr)
        acc.save()
        return False
    acc.threads_token = fresh["access_token"]
    acc.token_date = today.isoformat()
    lifetime = timedelta(seconds=int(fresh.get("expires_in") or TOKEN_LIFETIME_DAYS * 86400))
    acc.token_expires = (today + lifetime).isoformat()
    acc.save()
    return True


def _state_path(acc: Account) -> str:
    return os.path.join(acc.folder, "state.json")


def attempts_today(acc: Account, today: date | None = None) -> int:
    today = (today or date.today()).isoformat()
    try:
        with open(_state_path(acc), encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return 0
    return st.get("attempts", 0) if st.get("date") == today else 0


def note_attempt(acc: Account, today: date | None = None) -> None:
    today = today or date.today()
    _write_json(_state_path(acc), {"date": today.isoformat(), "attempts": attempts_today(acc, today) + 1})


def posted_today(acc: Account, today: date | None = None) -> bool:
    today = (today or date.today()).isoformat()
    return any(e.get("date") == today for e in acc.history())
