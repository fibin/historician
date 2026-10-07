# Запуск бота по расписанию (если pythonw не найден). Пишет лог в logs\<дата>.log
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"
python -m historian.main --due --log-dir logs
