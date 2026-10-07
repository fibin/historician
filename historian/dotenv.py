"""Мини-загрузчик .env: KEY=VALUE построчно, без внешних зависимостей."""
import os


def load(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def save(updates: dict[str, str], path: str = ".env") -> None:
    """Записывает значения в .env: заменяет существующие строки, новые добавляет в конец."""
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    pending = dict(updates)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in pending:
            lines[i] = f"{key}={pending.pop(key)}"
    lines += [f"{k}={v}" for k, v in pending.items()]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.environ.update(updates)
