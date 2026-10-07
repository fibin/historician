"""Короткое вертикальное видео (YouTube Shorts, TikTok, Reels) из готового поста. Всё бесплатно и на этом компьютере:

1. ИИ аккаунта пишет закадровый текст на 35–50 секунд, разбитый на сцены, и что показать в каждой.
2. Edge TTS (голоса Microsoft, бесплатно) озвучивает и отдаёт время каждого слова.
3. Кадры: картинки с Wikimedia Commons, медленное приближение или отдаление.
4. Субтитры по 1–3 слова, текущее слово подсвечено.
5. FFmpeg собирает 1080×1920 и кладёт рядом текст с названием и описанием для загрузки.

Нужны FFmpeg (winget install Gyan.FFmpeg) и пакет edge-tts (ставится из requirements.txt).
Фоновая музыка по желанию: положите mp3 в папку music/ рядом с Historian.bat, бот возьмёт случайный трек.
"""
import asyncio
import glob
import json
import os
import random
import re
import shutil
import subprocess
import tempfile

import requests

from . import engines, images

W, H, FPS = 1080, 1920, 30
ZOOM = 0.12           # насколько приближается кадр за сцену
MUSIC_DIR = "music"
MUSIC_VOLUME = 0.12

SCRIPT_SYSTEM = """Ты сценарист коротких вертикальных видео (YouTube Shorts, TikTok, Reels) для аккаунта.
Тема аккаунта и пожелания к контенту:
{theme}

Из готовой публикации сделай закадровый текст на 35–50 секунд (90–130 слов). Язык: {language}.
- Сцена 1 — крючок: самая неожиданная деталь, понятная без контекста, цепляет за первые две секунды.
  Не начинай с «Знаете ли вы», с даты или с «Сегодня расскажу».
- Дальше 3–5 сцен, в каждой одна мысль. Короткие фразы для чтения вслух: без скобок, ссылок, эмодзи, сокращений.
- Последняя сцена — короткий вывод или вопрос зрителям, на который хочется ответить в комментариях.
- Только факты из публикации, ничего не выдумывай. Спорное так и называй спорным.

Для каждой сцены image_query: что показать в кадре, поисковый запрос на английском для Wikimedia Commons
(портрет человека, место, здание, предмет, гравюра, карта, картина о событии). Конкретно: имя или название + что именно.
title: название видео до 70 символов на языке видео, интригующее, без кликбейта.
description: одно-два предложения под видео на языке видео и 3–5 хештегов."""

SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "image_query": {"type": "string"}},
            "required": ["text", "image_query"], "additionalProperties": False}},
        "title": {"type": "string"},
        "description": {"type": "string"},
    },
    "required": ["scenes", "title", "description"],
    "additionalProperties": False,
}

# Голоса Edge TTS по языку поста; другой голос можно задать переменной HISTORIAN_VOICE.
VOICES = [
    (("укр", "ukr"), "uk-UA-OstapNeural"),
    (("рус", "russ"), "ru-RU-DmitryNeural"),
    (("pol", "пол"), "pl-PL-MarekNeural"),
    (("deu", "germ", "нем"), "de-DE-ConradNeural"),
    (("esp", "span", "исп"), "es-ES-AlvaroNeural"),
    (("fran", "фран"), "fr-FR-HenriNeural"),
    (("eng", "англ"), "en-US-AndrewNeural"),
]
DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"


def voice_for(language: str) -> str:
    if os.environ.get("HISTORIAN_VOICE"):
        return os.environ["HISTORIAN_VOICE"]
    lang = language.lower()
    return next((v for keys, v in VOICES if any(k in lang for k in keys)), DEFAULT_VOICE)


def ffmpeg_bin(name: str = "ffmpeg") -> str:
    exe = os.environ.get(f"{name.upper()}_BIN") or shutil.which(name)
    if not exe:
        raise SystemExit("Не найден FFmpeg. В PowerShell выполните: winget install Gyan.FFmpeg "
                         "Потом закройте и снова откройте Historian.bat.")
    return exe


def _ff(args: list[str], cwd: str | None = None) -> None:
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg: {proc.stderr[-1500:]}")


def duration(path: str) -> float:
    proc = subprocess.run([ffmpeg_bin("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=nw=1:nk=1", path], capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return float(proc.stdout.strip())


# --- сценарий -----------------------------------------------------------------------------------------

def write_script(story: dict, engine: str, theme: str, language: str) -> dict:
    system = SCRIPT_SYSTEM.replace("{theme}", theme.strip()).replace("{language}", language.strip())
    user = (f"Публикация: {story.get('subject', '')} — {story.get('topic', '')}\n\n"
            + "\n\n".join(story["threads_posts"]))
    script = engines.ask(engine, system, user, SCHEMA)
    script["scenes"] = [s for s in script.get("scenes") or [] if s.get("text", "").strip()]
    if not script["scenes"]:
        raise RuntimeError("ИИ не написал сценарий видео")
    return script


# --- озвучка ------------------------------------------------------------------------------------------

async def _speak(text: str, voice: str, path: str) -> list[tuple[float, float, str]]:
    import edge_tts

    words = []
    comm = edge_tts.Communicate(text, voice, rate="+8%", boundary="WordBoundary")
    with open(path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append((start, start + chunk["duration"] / 1e7, chunk["text"]))
    return words


def speak(text: str, voice: str, path: str) -> list[tuple[float, float, str]]:
    """Озвучивает текст в mp3 и возвращает слова с временем начала и конца в секундах."""
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        raise SystemExit("Не установлен edge-tts. В PowerShell выполните: python -m pip install edge-tts")
    return asyncio.run(_speak(text, voice, path))


# --- кадры --------------------------------------------------------------------------------------------

def pick_images(scenes: list[dict], fallback: list[dict]) -> list[dict | None]:
    """Картинка на каждую сцену: по запросу сцены, иначе из вариантов поста, иначе предыдущая."""
    used, out = set(), []
    for scene in scenes:
        options = images.find([scene.get("image_query", "")], want=4)
        img = next((i for i in options if i["page"] not in used), None)
        img = img or next((i for i in fallback if i["page"] not in used), None) or (out[-1] if out else None)
        if img:
            used.add(img["page"])
        out.append(img)
    return out


def download(img: dict, path: str) -> bool:
    try:
        r = requests.get(img["url"], headers={"User-Agent": images.UA}, timeout=60)
        r.raise_for_status()
    except Exception:
        return False
    with open(path, "wb") as f:
        f.write(r.content)
    return True


def still(src: str | None, out: str) -> None:
    """Кадр 1080×1920: картинка целиком по центру на размытом и притемнённом фоне из неё же.
    Без картинки — тёмный фон."""
    if not src:
        _ff(["-f", "lavfi", "-i", f"color=c=0x1f1d1a:s={W}x{H}", "-frames:v", "1", out])
        return
    graph = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:4,"
             f"eq=brightness=-0.22[bg];[0:v]scale={W - 60}:{int(H * 0.62)}:force_original_aspect_ratio=decrease[fg];"
             f"[bg][fg]overlay=(W-w)/2:(H-h)/2-180,format=rgb24")
    _ff(["-i", src, "-filter_complex", graph, "-frames:v", "1", out])


def clip(still_path: str, seconds: float, out: str, zoom_in: bool) -> None:
    """Медленное приближение (или отдаление) кадра на всю длину сцены."""
    n = max(1, round(seconds * FPS))
    z = f"1+{ZOOM}*on/{n}" if zoom_in else f"{1 + ZOOM}-{ZOOM}*on/{n}"
    # кадр увеличен вдвое перед zoompan: иначе картинка дрожит при медленном зуме
    vf = (f"scale={W * 2}:{H * 2},zoompan=z='{z}':d={n}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
          f":s={W}x{H}:fps={FPS},format=yuv420p")
    _ff(["-i", still_path, "-vf", vf, "-frames:v", str(n), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-r", str(FPS), out])


# --- субтитры -----------------------------------------------------------------------------------------

ASS_HEAD = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Arial,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,2,70,70,380,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
HIGHLIGHT = r"{\c&H0030D5FF&}"  # золотистый, BGR
PLAIN = r"{\c&H00FFFFFF&}"


def _ts(t: float) -> str:
    cs = max(0, round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def chunks(words: list[tuple[float, float, str]], size: int = 3, gap: float = 0.35) -> list[list]:
    """Слова по 1–3 на экран; новая группа и после паузы в речи."""
    out: list[list] = []
    for w in words:
        if out and len(out[-1]) < size and w[0] - out[-1][-1][1] < gap and not re.search(r"[.!?…]$", out[-1][-1][2]):
            out[-1].append(w)
        else:
            out.append([w])
    return out


def subtitles(words: list[tuple[float, float, str]], end: float) -> str:
    lines = [ASS_HEAD]
    groups = chunks(words)
    for gi, group in enumerate(groups):
        group_end = groups[gi + 1][0][0] if gi + 1 < len(groups) else end
        group_end = min(group_end, group[-1][1] + 0.6)
        for wi, (start, _, _) in enumerate(group):
            stop = group[wi + 1][0] if wi + 1 < len(group) else group_end
            text = " ".join((HIGHLIGHT if i == wi else PLAIN) + w[2].replace("{", "(").replace("}", ")")
                            for i, w in enumerate(group))
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(stop)},Main,,0,0,0,,{text}\n")
    return "".join(lines)


# --- сборка -------------------------------------------------------------------------------------------

def _fonts(folder: str) -> str:
    """Шрифт субтитров кладём рядом с ними: FFmpeg для Windows не всегда находит системные шрифты сам."""
    os.makedirs(folder, exist_ok=True)
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for name in ("arial.ttf", "arialbd.ttf"):
        src = os.path.join(windir, "Fonts", name)
        if os.path.exists(src):
            shutil.copy(src, folder)
    return ":fontsdir=fonts"


def _music() -> str | None:
    tracks = glob.glob(os.path.join(MUSIC_DIR, "*.mp3"))
    return random.choice(tracks) if tracks else None


def _description(script: dict, pics: list[dict | None]) -> str:
    credits = []
    for img in pics:
        if img and img["page"] not in {c[0] for c in credits}:
            who = f"{img['author']}, " if img.get("author") else ""
            credits.append((img["page"], f"{who}{img['license']}: {img['page']}"))
    text = f"{script['title']}\n\n{script['description']}"
    if credits:
        text += "\n\n🖼 Wikimedia Commons\n" + "\n".join(c[1] for c in credits)
    return text


def make(story: dict, engine: str, theme: str, language: str, out_path: str, progress=lambda msg: None) -> dict:
    """Делает видео out_path (.mp4) и рядом .json с названием, описанием и сценарием. Возвращает этот json."""
    ffmpeg_bin()  # до долгой работы ИИ проверяем, что собирать будет чем
    progress("Пишу сценарий")
    script = write_script(story, engine, theme, language)
    scenes = script["scenes"]
    voice = voice_for(language)
    with tempfile.TemporaryDirectory() as tmp:
        progress("Озвучиваю")
        words, offset, lengths = [], 0.0, []
        for i, scene in enumerate(scenes):
            mp3 = os.path.join(tmp, f"a{i}.mp3")
            spoken = speak(scene["text"], voice, mp3)
            length = duration(mp3)
            words += [(offset + s, offset + e, t) for s, e, t in spoken]
            lengths.append(length)
            offset += length
        with open(os.path.join(tmp, "audio.txt"), "w", encoding="utf-8") as f:
            f.writelines(f"file 'a{i}.mp3'\n" for i in range(len(scenes)))
        _ff(["-f", "concat", "-safe", "0", "-i", "audio.txt", "-c:a", "aac", "-b:a", "160k", "voice.m4a"], cwd=tmp)

        progress("Подбираю кадры")
        pics = pick_images(scenes, story.get("images") or [])
        progress("Собираю видео")
        files: dict[str, str | None] = {}
        for i, (img, length) in enumerate(zip(pics, lengths)):
            src = None
            if img:
                src = files.get(img["page"])
                if src is None and download(img, os.path.join(tmp, f"img{i}")):
                    src = files[img["page"]] = os.path.join(tmp, f"img{i}")
            still(src, os.path.join(tmp, f"s{i}.png"))
            clip(os.path.join(tmp, f"s{i}.png"), length, os.path.join(tmp, f"c{i}.mp4"), zoom_in=i % 2 == 0)
        with open(os.path.join(tmp, "clips.txt"), "w", encoding="utf-8") as f:
            f.writelines(f"file 'c{i}.mp4'\n" for i in range(len(scenes)))
        _ff(["-f", "concat", "-safe", "0", "-i", "clips.txt", "-c", "copy", "video.mp4"], cwd=tmp)
        with open(os.path.join(tmp, "subs.ass"), "w", encoding="utf-8") as f:
            f.write(subtitles(words, offset))

        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        inputs = ["-i", "video.mp4", "-i", "voice.m4a"]
        audio = "[1:a]anull[a]"
        music = _music()
        if music:
            inputs += ["-stream_loop", "-1", "-i", os.path.abspath(music)]
            audio = f"[2:a]volume={MUSIC_VOLUME}[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]"
        # путь к субтитрам относительный (cwd=tmp): в фильтре subtitles пути Windows с C:\ ломаются
        fonts = _fonts(os.path.join(tmp, "fonts"))
        _ff([*inputs, "-filter_complex", f"[0:v]subtitles=subs.ass{fonts}[v];{audio}", "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", os.path.abspath(out_path)],
            cwd=tmp)

    info = {"title": script["title"], "description": _description(script, pics),
            "script": [s["text"] for s in scenes], "voice": voice, "seconds": round(offset, 1),
            "images": [img and img["page"] for img in pics]}
    with open(os.path.splitext(out_path)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    return info


def info(out_path: str) -> dict | None:
    """Данные готового видео (рядом с .mp4 лежит .json) или None, если видео ещё нет."""
    meta = os.path.splitext(out_path)[0] + ".json"
    if not (os.path.exists(out_path) and os.path.exists(meta)):
        return None
    with open(meta, encoding="utf-8") as f:
        return json.load(f)
