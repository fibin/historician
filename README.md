# Historian — бот малоизвестных исторических историй

Каждый день бот:
1. **Ищет** в интернете малоизвестную историю о конкретном человеке: привычки, причуды, эпизоды из мемуаров,
   дневников и писем современников. Общеизвестные факты отбрасываются, история должна подтверждаться
   минимум двумя источниками (Claude + веб-поиск, `historian/research.py`).
2. **Пишет** посты: тред для X (части ≤ 280 символов) и пост/цепочку для Threads (≤ 500), со ссылкой на источник
   (`historian/writer.py`). Длины проверяются кодом, лишнее аккуратно режется по предложениям.
3. **Публикует** в X и Threads, только если публикация явно включена. Иначе сохраняет черновик в `out/`.
4. **Запоминает** человека и тему в `data/history.json`, чтобы не повторяться (люди за последние ~2 месяца
   исключаются полностью, темы за всё время передаются модели как «уже было»).

## Локальный запуск

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
python -m historian.main                       # только черновик, ничего не публикует
python -m historian.main --from-draft out/2026-10-07.json --publish   # опубликовать проверенный черновик
python -m historian.main --publish --no-threads                       # только в X
python -m pytest -q tests                      # тесты (без сети и ключей)
```

Настройки через переменные окружения: `HISTORIAN_LANGUAGE` (язык постов, по умолчанию `русский`),
`HISTORIAN_MODEL` (по умолчанию `claude-opus-5-5`), `HISTORIAN_PUBLISH=true` (публиковать без флага).

## Ключи

**Claude API** — `ANTHROPIC_API_KEY` из console.anthropic.com.

**X (x.com)** — в developer.x.com создать проект и приложение, в User authentication settings включить
права *Read and write*, затем сгенерировать Access Token и Secret **после** смены прав.
Нужны: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`.
Публикация через API у X платная, тариф смотрите в консоли разработчика.

**Threads** — в developers.facebook.com создать приложение с продуктом *Threads API*, разрешения
`threads_basic` и `threads_content_publish`, добавить свой аккаунт тестировщиком, получить
**долгоживущий** токен (60 дней) и свой Threads user id. Нужны: `THREADS_USER_ID`, `THREADS_ACCESS_TOKEN`.
Продлить токен до истечения: `python -m historian.main --refresh-threads-token` (выведет новый токен,
его нужно обновить в секретах).

## Ежедневный запуск через GitHub Actions

`.github/workflows/daily.yml` запускается каждый день в 09:00 UTC.

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
  llm.py         вызов Claude: стриминг, продолжение долгого поиска, обработка отказа
  textfit.py     подсчёт длины по правилам X и нарезка
  history.py     журнал опубликованного
  publishers/    x.py (API v2, OAuth 1.0a), threads.py (Threads Graph API)
```
