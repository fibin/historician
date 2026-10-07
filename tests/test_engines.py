import json

import pytest

from historian import engines

STORY = {"person": "Тихо Браге", "topic": "лось", "threads_posts": ["Пост"],
         "sources": ["https://example.com"], "dossier": "Д"}


@pytest.fixture
def fake(monkeypatch):
    calls = {}

    def install(stdout="", write=None):
        class Proc:
            returncode = 0
            stderr = ""

        def run(cmd, input, **kw):
            calls["cmd"], calls["input"] = cmd, input
            if write:
                out = cmd[cmd.index("-o") + 1]
                with open(out, "w", encoding="utf-8") as f:
                    f.write(write)
            p = Proc()
            p.stdout = stdout
            return p

        monkeypatch.setattr(engines.shutil, "which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(engines.subprocess, "run", run)
        return calls
    return install


def test_claude_code_reads_structured_output(fake):
    calls = fake(stdout=json.dumps({"is_error": False, "structured_output": STORY}))
    story = engines.generate_story("claude-code", "- Пётр I: x")
    assert story["engine"] == "claude-code" and story["dossier"] == "Д"
    assert "--json-schema" in calls["cmd"] and "WebSearch,WebFetch" in calls["cmd"]
    assert "Пётр I" in calls["input"]


def test_codex_uses_search_schema_and_reads_last_message(fake):
    calls = fake(write=json.dumps(STORY, ensure_ascii=False))
    story = engines.generate_story("codex", "-")
    cmd = calls["cmd"]
    assert cmd[1:3] == ["--search", "exec"] and "--output-schema" in cmd and cmd[-1] == "-"
    assert "read-only" in cmd
    assert story["person"] == "Тихо Браге" and story["engine"] == "codex"
    # промпт целиком идёт через stdin, в аргументах нет переносов строк
    assert "Ты историк" in calls["input"] and not any("\n" in a for a in cmd)


def test_gemini_parses_fenced_json(fake):
    reply = "Вот результат:\n```json\n" + json.dumps(STORY, ensure_ascii=False) + "\n```"
    calls = fake(stdout=json.dumps({"response": reply}))
    story = engines.generate_story("gemini", "-")
    assert story["topic"] == "лось" and story["engine"] == "gemini"
    assert "--allowed-tools=google_web_search,web_fetch" in calls["cmd"] and not any("\n" in a for a in calls["cmd"])


def test_missing_fields_are_reported(fake):
    fake(stdout=json.dumps({"response": json.dumps({"person": "X"})}))
    with pytest.raises(RuntimeError, match="нет полей"):
        engines.generate_story("gemini", "-")


def test_missing_program_explains_setup(monkeypatch):
    monkeypatch.setattr(engines.shutil, "which", lambda name: None)
    monkeypatch.delenv("CODEX_BIN", raising=False)
    with pytest.raises(SystemExit, match="codex"):
        engines.generate_story("codex", "-")
