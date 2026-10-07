import json
import os
import shutil
import subprocess

import pytest

from historian import accounts, engines, images, main, video, web

WORDS = [(0.1, 0.4, "У"), (0.4, 0.9, "данського"), (0.9, 1.5, "астронома."), (1.6, 2.0, "Був"), (2.6, 3.0, "лось")]


def test_voice_follows_post_language(monkeypatch):
    monkeypatch.delenv("HISTORIAN_VOICE", raising=False)
    assert video.voice_for("українська") == "uk-UA-OstapNeural"
    assert video.voice_for("English") == "en-US-AndrewNeural"
    assert video.voice_for("suomi") == video.DEFAULT_VOICE
    monkeypatch.setenv("HISTORIAN_VOICE", "uk-UA-PolinaNeural")
    assert video.voice_for("українська") == "uk-UA-PolinaNeural"


def test_subtitles_group_words_and_highlight_current():
    groups = video.chunks(WORDS)
    # точка закрывает группу, длинная пауза начинает новую
    assert [[w[2] for w in g] for g in groups] == [["У", "данського", "астронома."], ["Був"], ["лось"]]
    ass = video.subtitles(WORDS, 3.5)
    events = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    assert len(events) == 5
    assert events[1].startswith("Dialogue: 0,0:00:00.40,0:00:00.90,Main")
    assert video.HIGHLIGHT + "данського" in events[1] and video.PLAIN + "У" in events[1]


def test_script_comes_from_account_ai(monkeypatch):
    seen = {}

    def ask(engine, system, user, schema, search=False, timeout=900):
        seen.update(engine=engine, system=system, user=user, search=search)
        return {"scenes": [{"text": " ", "image_query": "x"}, {"text": "Лось.", "image_query": "moose"}],
                "title": "T", "description": "D"}
    monkeypatch.setattr(engines, "ask", ask)
    script = video.write_script({"subject": "Браге", "topic": "лось", "threads_posts": ["Пост один"]},
                                "codex", "історія", "українська")
    assert [s["text"] for s in script["scenes"]] == ["Лось."]  # пустые сцены выброшены
    assert seen["engine"] == "codex" and not seen["search"] and "Пост один" in seen["user"]
    assert "Язык: українська" in seen["system"] and "{theme}" not in seen["system"]


def test_missing_ffmpeg_is_explained(monkeypatch):
    monkeypatch.setattr(video.shutil, "which", lambda name: None)
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    with pytest.raises(SystemExit, match="winget install Gyan.FFmpeg"):
        video.make({"threads_posts": ["x"]}, "claude-code", "t", "uk", "out.mp4")


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="нужен FFmpeg")
def test_make_builds_vertical_video(tmp_path, monkeypatch):
    scenes = [{"text": "Перша сцена тут.", "image_query": "a"}, {"text": "Друга сцена.", "image_query": "zzz"}]
    monkeypatch.setattr(engines, "ask", lambda *a, **k: {"scenes": scenes, "title": "Назва", "description": "Опис"})

    def speak(text, voice, path):
        n = len(text.split())
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
                        "-t", str(0.4 * n + 0.2), path], check=True)
        return [(0.1 + i * 0.4, 0.45 + i * 0.4, w) for i, w in enumerate(text.split())]
    monkeypatch.setattr(video, "speak", speak)
    pic = tmp_path / "p.jpg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x480",
                    "-frames:v", "1", str(pic)], check=True)
    img = {"page": "https://c/File:p", "url": str(pic), "author": "A", "license": "CC BY 4.0"}
    monkeypatch.setattr(images, "find", lambda qs, want=6: [img] if qs == ["a"] else [])
    monkeypatch.setattr(video, "download", lambda i, path: shutil.copy(i["url"], path) or True)

    out = tmp_path / "v" / "post.mp4"
    stages = []
    info = video.make({"threads_posts": ["x"], "images": []}, "claude-code", "t", "українська", str(out), stages.append)
    assert stages == ["Пишу сценарий", "Озвучиваю", "Подбираю кадры", "Собираю видео"]
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    assert probe == "1080,1920"
    assert info["images"] == [img["page"], img["page"]]  # для второй сцены ничего не нашлось: тот же кадр
    assert "A, CC BY 4.0: https://c/File:p" in info["description"]
    assert video.info(str(out))["title"] == "Назва"


def test_web_video_job_uses_draft_name(monkeypatch):
    acc = accounts.ensure()[0]
    draft = main.save_draft({"subject": "X", "topic": "t", "threads_posts": ["p"], "sources": []}, acc.out_dir)
    made = {}

    def make(story, engine, theme, language, out_path, progress):
        progress("Озвучиваю")
        made.update(path=out_path, stage=job["stage"])
        open(out_path, "wb").close()
        with open(out_path[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump({"title": "T", "description": "D"}, f)
    monkeypatch.setattr(video, "make", make)
    os.makedirs(os.path.join(acc.folder, "video"))
    job = web.job_for(acc)
    web.do_video(acc.id, job)
    assert made["path"].endswith(os.path.join("video", os.path.basename(draft)[:-5] + ".mp4"))
    assert made["stage"] == "Озвучиваю" and job["stage"] == ""
    assert web.state(acc.id)["job"]["video"]["title"] == "T"
