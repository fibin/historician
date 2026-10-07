"""Режим подписки: историю ищет и пишет Claude Code (`claude -p`), вошедший в вашу подписку Claude.

Ключ API не нужен. Те же промпты, что и в режиме API (research.SYSTEM + writer.SYSTEM).
"""
import json
import os
import shutil
import subprocess

from . import research, writer

SCHEMA = {
    **writer.SCHEMA,
    "properties": {**writer.SCHEMA["properties"], "dossier": {"type": "string"}},
    "required": writer.SCHEMA["required"] + ["dossier"],
}

SYSTEM = (
    research.SYSTEM
    + "\n\n---\nКогда досье готово, сам напиши по нему посты.\n\n"
    + writer.SYSTEM
    + "\n\nВ поле dossier положи досье целиком (в формате выше)."
)


def find_claude() -> str:
    exe = os.environ.get("CLAUDE_CODE_BIN") or shutil.which("claude")
    if not exe:
        raise SystemExit("Не найден Claude Code (команда claude). Установите его и войдите: claude")
    return exe


def generate_story(history_summary: str, timeout: int = 1800) -> dict:
    prompt = (
        "Найди сегодняшнюю историю и напиши посты.\n\n"
        "Эти люди и сюжеты уже были, их не повторяй (людей из последних двух месяцев не бери вовсе):\n"
        f"{history_summary}"
    )
    cmd = [
        find_claude(), "-p",
        "--model", os.environ.get("HISTORIAN_CC_MODEL", "opus"),
        "--tools", "WebSearch,WebFetch",
        "--allowedTools", "WebSearch,WebFetch",
        "--system-prompt", SYSTEM,
        "--json-schema", json.dumps(SCHEMA, ensure_ascii=False),
        "--output-format", "json",
    ]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"claude завершился с кодом {proc.returncode}: {proc.stderr or proc.stdout}")
    result = json.loads(proc.stdout)
    if result.get("is_error") or not result.get("structured_output"):
        raise RuntimeError(f"claude не вернул историю: {result.get('result') or result}")
    return result["structured_output"]
