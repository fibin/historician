# Один ежедневный запуск бота. Пишет лог в logs\<дата>.log
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
New-Item -ItemType Directory -Force -Path logs | Out-Null
$log = "logs\$(Get-Date -Format yyyy-MM-dd).log"
$env:PYTHONIOENCODING = "utf-8"
python -m historian.main *>> $log
