# Регистрирует ежедневную задачу Windows. Запуск: powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 [-Time 10:00]
param([string]$Time = "10:00")
$script = Join-Path $PSScriptRoot "run_daily.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
# Если компьютер был выключен в это время, задача запустится при следующем включении.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "Historian bot" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Готово: бот будет запускаться каждый день в $Time"
