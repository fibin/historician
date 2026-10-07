"""Окно бота в браузере: настройки Threads, «Сгенерировать», правка постов, «Опубликовать».

Запуск: двойной клик по Historian.bat или `python -m historian.web`.
Сервер слушает только 127.0.0.1, страница открывается в браузере сама.
"""
import glob
import json
import os
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import dotenv, engines, history, main
from .config import HISTORY_PATH, THREADS_LIMIT, ThreadsCredentials
from .publishers import threads as threads_pub

PORT = int(os.environ.get("HISTORIAN_PORT", "8765"))
OUT_DIR = "out"

_lock = threading.Lock()
state = {"status": "idle", "message": "", "started": None, "story": None,
         "draft": None, "published": False, "link": None}


def _is_published(story: dict) -> bool:
    return any(e["person"] == story.get("person") and e["topic"] == story.get("topic")
               for e in history.load(HISTORY_PATH))


def load_latest_draft() -> None:
    drafts = sorted(glob.glob(os.path.join(OUT_DIR, "*.json")))
    if not drafts:
        return
    with open(drafts[-1], encoding="utf-8") as f:
        story = json.load(f)
    state.update(story=story, draft=drafts[-1], published=_is_published(story))


def current_engine() -> str:
    name = os.environ.get("HISTORIAN_ENGINE", "claude-code")
    return name if name in engines.ENGINES else "claude-code"


def settings() -> dict:
    return {"user_id": os.environ.get("THREADS_USER_ID", ""),
            "has_token": bool(os.environ.get("THREADS_ACCESS_TOKEN")),
            "username": os.environ.get("THREADS_USERNAME", ""),
            "engine": current_engine(),
            "engines": [{"id": k, "label": v["label"], "setup": v["setup"], "available": engines.available(k)}
                        for k, v in engines.ENGINES.items()]}


def set_engine(name: str) -> dict:
    if name not in engines.ENGINES:
        raise ValueError(f"Неизвестный ИИ: {name}")
    dotenv.save({"HISTORIAN_ENGINE": name})
    return settings()


def _run(status: str, job) -> bool:
    with _lock:
        if state["status"] in ("generating", "publishing"):
            return False
        state.update(status=status, message="", started=time.time())

    def worker():
        try:
            job()
            state.update(status="idle")
        except BaseException as e:  # SystemExit из main тоже показываем пользователю
            traceback.print_exc()
            state.update(status="error", message=str(e) or e.__class__.__name__)

    threading.Thread(target=worker, daemon=True).start()
    return True


def do_generate() -> None:
    story = main.generate(current_engine(), history.load(HISTORY_PATH))
    path = main.save_draft(story, OUT_DIR)
    state.update(story=story, draft=path, published=False, link=None)


def do_publish(posts: list[str]) -> None:
    story = dict(state["story"], threads_posts=posts)
    story = main.fit_story(story)
    main.check_not_recent(story, history.load(HISTORY_PATH))
    posted = main.publish_and_record(story)
    if state["draft"]:
        main.save_draft(story, OUT_DIR)
    creds = ThreadsCredentials.from_env()
    state.update(story=story, published=True, link=threads_pub.permalink(creds, posted["threads"]))


def save_settings(user_id: str, token: str) -> dict:
    token = token.strip() or os.environ.get("THREADS_ACCESS_TOKEN", "")
    if not token:
        raise ValueError("Вставьте токен Threads")
    me = threads_pub.whoami(token)  # заодно проверяем, что токен рабочий
    user_id = user_id.strip() or me["id"]
    if user_id != me["id"]:
        raise ValueError(f"Токен принадлежит аккаунту @{me['username']} с ID {me['id']}, а не {user_id}")
    dotenv.save({"THREADS_USER_ID": user_id, "THREADS_ACCESS_TOKEN": token,
                 "THREADS_USERNAME": me.get("username", "")})
    return settings()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/api/state":
            elapsed = int(time.time() - state["started"]) if state["started"] else 0
            return self._send(200, {**state, "elapsed": elapsed, "settings": settings(),
                                    "limit": THREADS_LIMIT})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        # Принимаем запросы только со своей страницы.
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self._send(403, {"error": "forbidden"})
        try:
            body = self._json()
            if self.path == "/api/settings":
                return self._send(200, save_settings(body.get("user_id", ""), body.get("token", "")))
            if self.path == "/api/engine":
                return self._send(200, set_engine(body.get("engine", "")))
            if self.path == "/api/generate":
                ok = _run("generating", do_generate)
                return self._send(200 if ok else 409, {"ok": ok})
            if self.path == "/api/publish":
                posts = [p.strip() for p in body.get("posts", []) if p.strip()]
                if not state["story"] or not posts:
                    raise ValueError("Нет черновика для публикации")
                if not ThreadsCredentials.from_env():
                    raise ValueError("Сначала сохраните ID и токен Threads")
                ok = _run("publishing", lambda: do_publish(posts))
                return self._send(200 if ok else 409, {"ok": ok})
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(400, {"error": str(e)})


PAGE = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Historian</title>
<style>
:root{--bg:#f4f1ea;--card:#fffdf8;--ink:#1f1d1a;--muted:#6f6a61;--line:#e2ddd2;--accent:#1f1d1a;--bad:#a8321e;--good:#2f6b3a}
@media (prefers-color-scheme: dark){:root{--bg:#171614;--card:#201f1c;--ink:#ece8df;--muted:#a19a8d;--line:#35322d;--accent:#ece8df;--bad:#e0745f;--good:#7cc08a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:760px;margin:0 auto;padding:28px 16px 60px}
h1{font:600 26px/1.2 Georgia,"Times New Roman",serif;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
h2{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 12px}
label{display:block;font-size:13px;color:var(--muted);margin:10px 0 4px}
input,textarea{width:100%;font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:9px 11px}
textarea{min-height:110px;resize:vertical}
button{font:600 15px system-ui,sans-serif;border-radius:8px;border:1px solid var(--accent);padding:10px 18px;cursor:pointer;background:var(--accent);color:var(--bg)}
button.ghost{background:transparent;color:var(--ink);border-color:var(--line);font-weight:500}
button:disabled{opacity:.45;cursor:default}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:14px}
.status{font-size:14px;color:var(--muted)}.status.err{color:var(--bad)}.status.ok{color:var(--good)}
.post{margin-bottom:12px}.meta{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);margin-top:4px}
.meta .over{color:var(--bad);font-weight:600}.x{border:none;background:none;color:var(--muted);padding:0;font-weight:400;font-size:12px}
.person{font:600 19px/1.3 Georgia,serif;margin:0}.topic{color:var(--muted);margin:2px 0 14px}
a{color:inherit}
.sources a{display:block;color:var(--muted);font-size:13px;word-break:break-all}
.spin{display:inline-block;width:14px;height:14px;border:2px solid var(--line);border-top-color:var(--ink);border-radius:50%;animation:s 1s linear infinite;vertical-align:-2px;margin-right:6px}
@keyframes s{to{transform:rotate(360deg)}}
select{width:100%;font:inherit;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:9px 11px}
details.card summary{cursor:pointer;font-weight:600;list-style:none}details.card summary::-webkit-details-marker{display:none}
details.card summary::before{content:"▸ ";color:var(--muted)}details[open].card summary::before{content:"▾ "}
.guide ol{padding-left:22px;margin:12px 0 0}.guide li{margin:0 0 12px}.guide ul{padding-left:18px;margin:6px 0 0;color:var(--muted)}
code{font:13px ui-monospace,Consolas,monospace;background:var(--bg);border:1px solid var(--line);border-radius:5px;padding:1px 5px;overflow-wrap:break-word}
.engine-note{font-size:13px;margin-top:6px}
</style></head><body><main>
<h1>Historian</h1><p class="sub">Малоизвестные истории для Threads</p>

<details class="card guide" id="guide"><summary>Как начать</summary>
<ol>
<li><b>Выберите ИИ</b> в блоке «ИИ для текстов» ниже. Если рядом написано «не установлен», выполните шаги под списком, а потом закройте и снова откройте Historian.bat.</li>
<li><b>Получите токен Threads</b> (один раз, токен живёт 60 дней):
<ul>
<li>Откройте <a href="https://developers.facebook.com/apps" target="_blank" rel="noopener">developers.facebook.com/apps</a> → <b>Create App</b> → сценарий <b>Access the Threads API</b> → создайте приложение.</li>
<li><b>Use cases</b> → <b>Access the Threads API</b> → <b>Customize</b> → <b>Permissions</b>: должны быть <code>threads_basic</code> и <code>threads_content_publish</code>.</li>
<li><b>App roles</b> → <b>Roles</b> → <b>Add People</b> → <b>Threads Tester</b> → впишите имя вашего аккаунта Threads.</li>
<li>Примите приглашение: <a href="https://www.threads.net" target="_blank" rel="noopener">threads.net</a> → Настройки → Аккаунт → Разрешения для сайтов → Приглашения → Принять.</li>
<li>Снова <b>Use cases</b> → <b>Customize</b> → <b>Settings</b> → <b>User Token Generator</b> → <b>Generate access token</b> → скопируйте.</li>
</ul></li>
<li><b>Вставьте токен</b> в блок «Аккаунт Threads» и нажмите «Сохранить». ID определится сам.</li>
<li>Нажмите <b>«Сгенерировать»</b> и подождите несколько минут, пока ИИ ищет историю.</li>
<li><b>Прочитайте посты</b>, при необходимости поправьте текст, удалите или добавьте пост.</li>
<li>Нажмите <b>«Опубликовать»</b>. Под кнопкой появится ссылка на пост в Threads.</li>
<li><b>Каждый день сам</b> (по желанию): в файле <code>.env</code> поставьте <code>HISTORIAN_PUBLISH=true</code>, затем в PowerShell в папке бота выполните
<code>powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Time 10:00</code>. Бот будет публиковать историю каждый день в 10:00 выбранным ИИ.</li>
</ol>
</details>

<section class="card"><h2>ИИ для текстов</h2>
<select id="engine"></select>
<div id="engineNote" class="engine-note"></div>
</section>

<section class="card"><h2>Аккаунт Threads</h2>
<div id="who" class="status"></div>
<label for="uid">THREADS_USER_ID <span style="font-weight:400">(можно оставить пустым, определится по токену)</span></label>
<input id="uid" autocomplete="off">
<label for="tok">Токен</label>
<input id="tok" type="password" autocomplete="off" placeholder="вставьте новый токен, чтобы заменить">
<div class="row"><button class="ghost" id="save">Сохранить</button><span id="saveMsg" class="status"></span></div>
</section>

<section class="card"><h2>История дня</h2>
<div class="row" style="margin-top:0"><button id="gen">Сгенерировать</button><span id="genMsg" class="status"></span></div>
<div id="draft" style="margin-top:16px"></div>
</section>
</main>
<script>
const $ = id => document.getElementById(id);
let st = null, limit = 500, editing = false;

async function api(path, body){
  const r = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  const j = await r.json(); if(!r.ok) throw new Error(j.error || 'Ошибка'); return j;
}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function mmss(s){return Math.floor(s/60)+':'+String(s%60).padStart(2,'0')}

function renderEngine(s){
  const sel = $('engine');
  sel.innerHTML = s.engines.map(e => `<option value="${e.id}" ${e.id === s.engine ? 'selected' : ''}>${esc(e.label)}${e.available ? '' : ' (не установлен)'}</option>`).join('');
  const e = s.engines.find(x => x.id === s.engine);
  $('engineNote').innerHTML = e.available
    ? '<span class="status ok">Готов к работе</span>'
    : '<span class="status err">Не установлен. Как подключить:</span><ol>' + e.setup.map(x => `<li>${esc(x)}</li>`).join('') + '</ol>';
}
function renderSettings(s){
  renderEngine(s);
  if(!s.has_token) $('guide').open = true;
  $('uid').value = $('uid').value || s.user_id;
  $('who').textContent = s.has_token ? ('Подключено' + (s.username ? ': @'+s.username : '')) : 'Токен ещё не сохранён';
  $('who').className = 'status ' + (s.has_token ? 'ok' : 'err');
}
function renderDraft(){
  const d = $('draft'); const s = st.story;
  if(!s){ d.innerHTML = '<p class="status">Черновиков пока нет. Нажмите «Сгенерировать», это займёт несколько минут.</p>'; $('guide').open = true; return; }
  const eng = st.settings.engines.find(e => e.id === s.engine);
  d.innerHTML = `<p class="person">${esc(s.person)}</p><p class="topic">${esc(s.topic)}${eng ? ' · ' + esc(eng.label) : ''}</p>
    <div id="posts"></div>
    <button class="ghost" id="add">+ Добавить пост</button>
    <div class="sources" style="margin-top:14px">${(s.sources||[]).map(u=>`<a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a>`).join('')}</div>
    <div class="row"><button id="pub">Опубликовать</button><span id="pubMsg" class="status"></span></div>`;
  s.threads_posts.forEach(addPost);
  $('add').onclick = () => { addPost(''); editing = true; };
  $('pub').onclick = publish;
}
function addPost(text){
  const wrap = document.createElement('div'); wrap.className = 'post';
  wrap.innerHTML = `<textarea></textarea><div class="meta"><span class="n"></span><button class="x">удалить</button></div>`;
  const ta = wrap.querySelector('textarea'); ta.value = text;
  const upd = () => { const n = ta.value.length; const el = wrap.querySelector('.n');
    el.textContent = n + ' / ' + limit + (n > limit ? ' (будет разбит на части)' : ''); el.className = 'n' + (n > limit ? ' over' : ''); };
  ta.oninput = () => { editing = true; upd(); }; upd();
  wrap.querySelector('.x').onclick = () => { wrap.remove(); editing = true; };
  $('posts').appendChild(wrap);
}
function renderStatus(){
  const busy = st.status === 'generating' || st.status === 'publishing';
  $('gen').disabled = busy;
  if($('pub')) $('pub').disabled = busy || st.published;
  const g = $('genMsg'), p = $('pubMsg');
  g.className = 'status'; g.innerHTML = '';
  if(p){ p.className = 'status'; p.innerHTML = ''; }
  if(st.status === 'generating') g.innerHTML = `<span class="spin"></span>Ищу историю… ${mmss(st.elapsed)}`;
  else if(st.status === 'publishing' && p) p.innerHTML = `<span class="spin"></span>Публикую…`;
  else if(st.status === 'error'){ const t = (p && st.story) ? p : g; t.className = 'status err'; t.textContent = st.message; }
  else if(st.published && p){ p.className = 'status ok';
    p.innerHTML = st.link ? `Опубликовано: <a href="${esc(st.link)}" target="_blank" rel="noopener">открыть в Threads</a>` : 'Уже опубликовано'; }
}
async function refresh(){
  const prev = st; st = await api('/api/state'); limit = st.limit;
  if(!prev) renderSettings(st.settings);
  const changed = !prev || JSON.stringify(prev.story) !== JSON.stringify(st.story);
  if(changed && !editing) renderDraft();
  renderStatus();
}
async function publish(){
  const posts = [...document.querySelectorAll('#posts textarea')].map(t => t.value);
  try { await api('/api/publish', {posts}); editing = false; await refresh(); }
  catch(e){ $('pubMsg').className = 'status err'; $('pubMsg').textContent = e.message; }
}
$('gen').onclick = async () => {
  if(st.story && !st.published && !confirm('Текущий черновик не опубликован. Сгенерировать новый?')) return;
  try { editing = false; await api('/api/generate', {}); await refresh(); }
  catch(e){ $('genMsg').className = 'status err'; $('genMsg').textContent = e.message; }
};
$('engine').onchange = async e => {
  try { const s = await api('/api/engine', {engine: e.target.value}); renderEngine(s); st.settings = s; }
  catch(err){ $('engineNote').innerHTML = `<span class="status err">${esc(err.message)}</span>`; }
};
$('save').onclick = async () => {
  $('saveMsg').className = 'status'; $('saveMsg').textContent = 'Проверяю токен…';
  try { const s = await api('/api/settings', {user_id: $('uid').value, token: $('tok').value});
    $('tok').value = ''; $('uid').value = s.user_id; renderSettings(s);
    $('saveMsg').className = 'status ok'; $('saveMsg').textContent = 'Сохранено'; }
  catch(e){ $('saveMsg').className = 'status err'; $('saveMsg').textContent = e.message; }
};
refresh(); setInterval(refresh, 2000);
</script></body></html>"""


def run() -> None:
    load_latest_draft()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"Historian открыт: {url}\nНе закрывайте это окно, пока работаете с ботом.")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
