"""Движки, которые ищут материал и пишут посты.

claude-code, codex и gemini работают через консольные программы, вошедшие в вашу подписку
(Claude, ChatGPT, аккаунт Google), поэтому ключ API не нужен. api — Claude API по ключу.
Всем движкам дают одни и те же промпты (research + writer, с темой и языком аккаунта) и одну схему ответа.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

from . import research, writer

SCHEMA = {
    **writer.SCHEMA,
    "properties": {**writer.SCHEMA["properties"], "dossier": {"type": "string"}},
    "required": writer.SCHEMA["required"] + ["dossier"],
}


def system_prompt(theme: str, language: str) -> str:
    return (
        research.system_prompt(theme)
        + "\n\n---\nКогда досье готово, сам напиши по нему посты.\n\n"
        + writer.system_prompt(theme, language)
        + "\n\nВ поле dossier положи досье целиком (в формате выше)."
    )


# label — для окна, bin — консольная программа, setup — как установить и войти (для подсказки в окне).
ENGINES = {
    "claude-code": {
        "label": "Claude (подписка Claude)", "bin": "claude",
        "setup": ["В PowerShell: irm https://claude.ai/install.ps1 | iex",
                  "Затем выполните claude и войдите своим аккаунтом Claude, после входа окно можно закрыть"],
    },
    "codex": {
        "label": "ChatGPT (подписка ChatGPT, Codex)", "bin": "codex",
        "setup": ["Установите Node.js с nodejs.org (кнопка LTS)",
                  "В PowerShell: npm install -g @openai/codex",
                  "Затем выполните codex и выберите «Sign in with ChatGPT»"],
    },
    "gemini": {
        "label": "Gemini (аккаунт Google)", "bin": "gemini",
        "setup": ["Установите Node.js с nodejs.org (кнопка LTS)",
                  "В PowerShell: npm install -g @google/gemini-cli",
                  "Затем выполните gemini и выберите «Login with Google»"],
    },
    "api": {
        "label": "Claude API (платный ключ)", "bin": None,
        "setup": ["Ключ создаётся на console.anthropic.com → API Keys, баланс пополняется там же",
                  "Впишите его в .env строкой ANTHROPIC_API_KEY=..."],
    },
}


def available(name: str) -> bool:
    spec = ENGINES[name]
    if spec["bin"] is None:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    return bool(_find(spec["bin"], required=False))


def _find(binary: str, required: bool = True) -> str | None:
    exe = os.environ.get(f"{binary.upper()}_BIN") or shutil.which(binary)
    if not exe and required:
        raise SystemExit(f"Не найдена программа {binary}. Установите её (см. «Как начать» в окне бота) и войдите.")
    return exe


def _user_prompt(history_summary: str, feedback: str = "") -> str:
    return research.user_prompt(history_summary, feedback) + "\n\nКогда досье готово, напиши посты."


def _run(cmd: list[str], stdin: str, timeout: int) -> str:
    # Длинный текст идёт через stdin, а в аргументах только короткие строки:
    # на Windows npm-программы запускаются через .cmd, и cmd.exe портит сложные аргументы.
    # CREATE_NO_WINDOW: при запуске по расписанию (pythonw) не открывать окно консоли.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, creationflags=flags)
    if proc.returncode != 0:
        raise RuntimeError(f"{os.path.basename(cmd[0])} завершился с кодом {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-2000:]}")
    return proc.stdout


def _parse_json_reply(text: str) -> dict:
    """Достаёт JSON-объект из ответа модели, даже если он обёрнут в ```json ... ```."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(raw)
    except ValueError:
        raise RuntimeError(f"Модель вернула не JSON: {text[:500]}")


OPTIONAL = {"image_queries"}  # без них пост просто выйдет без картинки


def _validate(story: dict) -> dict:
    missing = [k for k in SCHEMA["required"] if k not in story and k not in OPTIONAL]
    if missing or not isinstance(story.get("threads_posts"), list) or not story["threads_posts"]:
        raise RuntimeError(f"В ответе модели нет полей: {', '.join(missing) or 'threads_posts'}")
    return story


def _claude_code(system: str, user: str, schema: dict, search: bool, timeout: int) -> dict:
    tools = "WebSearch,WebFetch" if search else ""
    cmd = [
        _find("claude"), "-p",
        "--model", os.environ.get("HISTORIAN_CC_MODEL", "opus"),
        "--tools", tools,
        *(["--allowedTools", tools] if search else []),
        "--system-prompt", system,
        "--json-schema", json.dumps(schema, ensure_ascii=False),
        "--output-format", "json",
    ]
    result = json.loads(_run(cmd, user, timeout))
    if result.get("is_error") or not result.get("structured_output"):
        raise RuntimeError(f"claude не вернул ответ: {result.get('result') or result}")
    return result["structured_output"]


def _codex(system: str, user: str, schema: dict, search: bool, timeout: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        schema_path = os.path.join(tmp, "schema.json")
        out_path = os.path.join(tmp, "answer.json")
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False)
        cmd = [_find("codex"), *(["--search"] if search else []), "exec",
               "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
               "--cd", tmp, "--output-schema", schema_path, "-o", out_path]
        model = os.environ.get("HISTORIAN_CODEX_MODEL")
        if model:
            cmd += ["-m", model]
        _run(cmd + ["-"], system + "\n\n---\n\n" + user, timeout)
        with open(out_path, encoding="utf-8") as f:
            return _parse_json_reply(f.read())


def _gemini(system: str, user: str, schema: dict, search: bool, timeout: int) -> dict:
    prompt = (system + "\n\n---\n\n" + user
              + "\n\nОтветь ТОЛЬКО JSON-объектом по этой схеме, без пояснений:\n"
              + json.dumps(schema, ensure_ascii=False))
    cmd = [_find("gemini"), "--output-format", "json", "--approval-mode", "plan",
           *(["--allowed-tools=google_web_search,web_fetch"] if search else []),
           "-p", "Follow the instructions above."]
    model = os.environ.get("HISTORIAN_GEMINI_MODEL")
    if model:
        cmd += ["-m", model]
    result = json.loads(_run(cmd, prompt, timeout))
    if result.get("error"):
        raise RuntimeError(f"gemini: {result['error']}")
    return _parse_json_reply(result.get("response", ""))


def _api(system: str, user: str, schema: dict, search: bool, timeout: int) -> dict:
    import anthropic

    from . import llm
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 20}] if search else None
    response = llm.run(anthropic.Anthropic(), system=system, user=user, tools=tools, effort="medium",
                       output_config={"format": {"type": "json_schema", "schema": schema}}, max_tokens=16000)
    return json.loads(llm.text_of(response))


RUNNERS = {"claude-code": _claude_code, "codex": _codex, "gemini": _gemini, "api": _api}


def ask(engine: str, system: str, user: str, schema: dict, search: bool = False, timeout: int = 900) -> dict:
    """Один запрос к выбранному ИИ с ответом строго по схеме. search — разрешить поиск в интернете."""
    return RUNNERS[engine](system, user, schema, search, timeout)


def generate_story(engine: str, history_summary: str, theme: str, language: str, feedback: str = "",
                   timeout: int = 1800) -> dict:
    story = _validate(ask(engine, system_prompt(theme, language), _user_prompt(history_summary, feedback),
                          SCHEMA, search=True, timeout=timeout))
    story["engine"] = engine
    return story
