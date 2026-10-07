# Регистрирует задачу Windows «Historian bot»: каждый час бот проверяет, в каких аккаунтах пора публиковать.
# Время и галочка «Публиковать каждый день сам» задаются для каждого аккаунта в окне бота.
# Запуск: powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 (или кнопка «Включить расписание» в окне)
param([string]$Time = "")  # больше не нужен: время задаётся в окне для каждого аккаунта
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pyw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if ($pyw) {
    # pythonw работает без окна, поэтому раз в час на экране ничего не мелькает
    $action = New-ScheduledTaskAction -Execute $pyw -Argument "-m historian.main --due --log-dir logs" -WorkingDirectory $root
} else {
    $script = Join-Path $PSScriptRoot "run_daily.ps1"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $root `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
}
# Каждый день с 00:00, повтор каждый час в течение суток.
$trigger = New-ScheduledTaskTrigger -Daily -At "00:00"
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "00:00" `
    -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
# Если компьютер был выключен, задача запустится после включения. Второй экземпляр не запускается.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Historian bot" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Готово: бот каждый час проверяет, в каких аккаунтах пора публиковать."
