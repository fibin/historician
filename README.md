# Historian — бот малоизвестных исторических историй

Каждый день бот:
1. **Ищет** в интернете малоизвестную историю о конкретном человеке: привычки, причуды, эпизоды из мемуаров,
   дневников и писем современников. Общеизвестные факты отбрасываются, история должна подтверждаться
   минимум двумя источниками (Claude + веб-поиск, `historian/research.py`).
2. **Пишет** посты: пост или цепочку постов для Threads (каждый ≤ 500 символов), со ссылкой на источник
   (`historian/writer.py`). Длины проверяются кодом, лишнее аккуратно режется по предложениям.
3. **Публикует** в Threads, только если публикация явно включена. Иначе сохраняет черновик в `out/`.
4. **Запоминает** человека и тему в `data/history.json`, чтобы не повторяться (люди за последние ~2 месяца
   исключаются полностью, темы за всё время передаются модели как «уже было»).

## Локальный запуск

```bash
pip install -r requirements.txt
python -m historian.main                       # черновик через Claude Code (подписка)
python -m historian.main --engine api          # черновик через Claude API (нужен ANTHROPIC_API_KEY)
python -m historian.main --from-draft out/2026-10-07.json --publish   # опубликовать проверенный черновик
python -m pytest -q tests                      # тесты (без сети и ключей)
```

Настройки через переменные окружения: `HISTORIAN_LANGUAGE` (язык постов, по умолчанию `українська`),
`HISTORIAN_MODEL` (по умолчанию `claude-opus-5-5`), `HISTORIAN_PUBLISH=true` (публиковать без флага).

## Ключи

**Claude API** — нужен только для `--engine api`: `ANTHROPIC_API_KEY` из console.anthropic.com.

**Threads** — в developers.facebook.com создать приложение с продуктом *Threads API*, разрешения
`threads_basic` и `threads_content_publish`, добавить свой аккаунт тестировщиком, получить
**долгоживущий** токен (60 дней) и свой Threads user id. Нужны: `THREADS_USER_ID`, `THREADS_ACCESS_TOKEN`.
Продлить токен до истечения: `python -m historian.main --refresh-threads-token` (выведет новый токен,
его нужно обновить в секретах).

## Запуск на своём компьютере (Windows, на подписке Claude)

В этом режиме историю ищет и пишет **Claude Code**, вошедший в вашу подписку Claude,
поэтому ключ API не нужен. Тратятся лимиты подписки.

1. Установите [Python 3.12+](https://www.python.org/downloads/) (галочка «Add python.exe to PATH»)
   и [Git](https://git-scm.com/download/win).
2. Установите Claude Code и войдите своей подпиской. В PowerShell выполните
   `irm https://claude.ai/install.ps1 | iex`, затем `claude` и выберите вход через аккаунт Claude.
3. Скачайте бота и поставьте зависимости:
   ```powershell
   git clone https://github.com/fibin/historician
   cd historian
   pip install -r requirements.txt
   copy .env.example .env
   ```
4. Пробный запуск, только черновик: `python -m historian.main`. Займёт несколько минут,
   черновик появится в `out\`.
5. Ежедневный запуск:
   `powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Time 10:00`.
   Если компьютер был выключен в это время, бот запустится при следующем включении. Логи лежат в `logs\`.
6. Когда качество черновиков устроит, впишите ключи Threads в `.env` и поставьте `HISTORIAN_PUBLISH=true`.

## Ежедневный запуск через GitHub Actions (режим API)

Расписание в `.github/workflows/daily.yml` по умолчанию выключено; чтобы работать через API, раскомментируйте `schedule`.

1. Положите код в репозиторий на GitHub.
2. *Settings → Secrets and variables → Actions → Secrets*: добавьте все ключи выше.
3. Пока переменная `HISTORIAN_PUBLISH` не задана, бот только готовит черновик (он лежит в артефакте `draft`
   у каждого запуска). Посмотрите несколько черновиков, и когда качество устроит, задайте
   *Variables → `HISTORIAN_PUBLISH` = `true`*.
4. Ручной запуск: *Actions → Daily history post → Run workflow* (галочка «Опубликовать»).

После публикации workflow коммитит обновлённый `data/history.json`.

## Устройство

```
historian/
  main.py        запуск, черновик/публикация, повтор при дубле человека
  research.py    промпт исследователя + веб-поиск
  writer.py      промпт автора, JSON-схема постов
  claude_code.py режим подписки: запуск Claude Code
  llm.py         вызов Claude: стриминг, продолжение долгого поиска, обработка отказа
  textfit.py     проверка длины и нарезка
  history.py     журнал опубликованного
  publishers/    threads.py (Threads Graph API)
```
